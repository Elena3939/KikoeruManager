"""应用侧 Unix socket 客户端；故障不得隐式转为完整复制。"""
import os
import socket
import uuid

from .file_move_protocol import VERSION, encode, receive, identity


class HostMoveError(RuntimeError):
    pass


class HostMoveClient:
    def __init__(self, socket_path, timeout=30):
        self.socket_path = socket_path
        self.timeout = timeout

    def request(self, action, checkpoint=None, **payload):
        if not hasattr(socket, "AF_UNIX"):
            raise HostMoveError("当前运行环境不支持宿主 Unix socket，已保留来源")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout)
                connection.connect(self.socket_path)
                connection.sendall(encode({"version": VERSION, "action": action, "keepalive": True, **payload}))
                with connection.makefile("rb") as stream:
                    while True:
                        response = receive(stream)
                        if response.get("version") != VERSION or not response.get("pending"):
                            break
                        if checkpoint:
                            checkpoint()
            if response.get("version") != VERSION or not response.get("ok"):
                raise HostMoveError(response.get("error") or "宿主文件移动协议版本不匹配")
            return response["result"]
        except (OSError, ValueError, KeyError) as exc:
            raise HostMoveError("宿主文件移动执行器不可用或响应异常，已保留来源") from exc

    def probe(self, source, destination_parent):
        return self.request("probe", source=os.path.abspath(source),
                            destination_parent=os.path.abspath(destination_parent))

    def clone(self, source, destination, mapping_version, checkpoint, register=None, on_created=None):
        operation_id = str(uuid.uuid4())
        pending = os.path.join(os.path.dirname(destination),
                               ".kikoerumanager-clone-" + operation_id + ".part")
        checkpoint()
        if register:
            register(operation_id)
        try:
            result = self.request(
                "prepare", operation_id=operation_id, mapping_version=mapping_version,
                source=os.path.abspath(source), destination=os.path.abspath(pending),
                source_identity=identity(source), checkpoint=checkpoint,
            )
            checkpoint()
            if identity(pending) != result["destination_identity"]:
                raise HostMoveError("宿主克隆暂存身份已变化，拒绝发布")
            # 原子禁止覆盖；只发布本次执行器生成的独占暂存。
            os.link(pending, destination)
            if on_created:
                on_created(identity(destination))
            os.unlink(pending)
            self.request("release", operation_id=operation_id)
        except BaseException:
            # cancel 等待正在进行的 ioctl 退出；收不到确认时留下暂存供恢复核对。
            # 执行器从不删除来源或最终目标。
            try:
                self.request("cancel", operation_id=operation_id)
            except HostMoveError as exc:
                raise HostMoveError("无法确认宿主克隆已停止，保留来源和暂存等待核对") from exc
            raise
