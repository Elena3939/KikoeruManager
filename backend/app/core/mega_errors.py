"""MEGA SDK API 错误定义，不用于解释 MEGAcmd 进程退出码。"""

# 官方定义：https://github.com/meganz/sdk/blob/master/include/mega/types.h
MEGA_API_ERRORS = {
    -1: ("API_EINTERNAL", "MEGA 内部错误"),
    -2: ("API_EARGS", "请求参数无效"),
    -3: ("API_EAGAIN", "请求暂时失败，请等待后按指数退避重试"),
    -4: ("API_ERATELIMIT", "请求频率过高，请降低请求频率"),
    -5: ("API_EFAILED", "请求永久失败，直接重试同一请求无法解决"),
    -6: ("API_ETOOMANY", "对此资源的请求过多"),
    -7: ("API_ERANGE", "访问范围超出资源边界"),
    -8: ("API_EEXPIRED", "资源已过期"),
    -9: ("API_ENOENT", "资源不存在，请检查分享是否仍然有效"),
    -10: ("API_ECIRCULAR", "操作产生了循环关联"),
    -11: ("API_EACCESS", "访问被拒绝，没有操作该资源的权限"),
    -12: ("API_EEXIST", "资源已经存在"),
    -13: ("API_EINCOMPLETE", "请求未完成"),
    -14: ("API_EKEY", "加密或解密错误，请检查分享密钥"),
    -15: ("API_ESID", "MEGA 会话 ID 无效"),
    -16: ("API_EBLOCKED", "资源已被 MEGA 管理封锁，请更换有效分享；接口未提供具体封锁原因"),
    -17: ("API_EOVERQUOTA", "配额已超限；具体配额类型需结合操作判断"),
    -18: ("API_ETEMPUNAVAIL", "资源暂时不可用，请稍后重试"),
    -19: ("API_ETOOMANYCONNECTIONS", "此资源的连接数过多，请减少并发连接"),
    -20: ("API_EWRITE", "文件写入失败，或写入后的完整性校验失败"),
    -21: ("API_EREAD", "文件读取失败，或读取期间文件发生了意外变化"),
    -22: ("API_EAPPKEY", "应用密钥缺失或无效"),
    -23: ("API_ESSL", "SSL 证书验证失败"),
    -24: ("API_EGOINGOVERQUOTA", "剩余配额不足以完成操作"),
    -25: ("API_EROLLEDBACK", "强关联请求组已回滚"),
    -26: ("API_EMFAREQUIRED", "需要多因素身份验证"),
    -27: ("API_EMASTERONLY", "企业子账号无权执行此操作，仅主账号可执行"),
    -28: ("API_EBUSINESSPASTDUE", "企业账号已过期"),
    -29: ("API_EPAYWALL", "账号超过存储配额，受到付费限制"),
    -30: ("API_ESUBUSERKEYMISSING", "企业子账号尚未为管理员加密主密钥，当前操作被禁止"),
}


def mega_api_error_message(code: int) -> str:
    definition = MEGA_API_ERRORS.get(code)
    if definition is None:
        return f"MEGA 接口返回未知错误（错误码 {code}）"
    symbol, description = definition
    return f"MEGA：{description}（{symbol}，错误码 {code}）"
