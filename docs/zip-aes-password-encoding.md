# ZIP AES 中文密码编码

Linux 下部分 Windows 工具制作的 WinZip AES ZIP 按 GBK 等本地编码保存密码字节。相同中文密码按 UTF-8 传给 7zz 会返回 Wrong password。

公共 7zz 命令入口在执行前，对非 ASCII 密码读取 ZIP 中央目录和至多三个 AES 条目的本地头、盐、两字节密码校验值，使用标准库 PBKDF2 识别编码并按归档指纹缓存。读取与派生在线程中完成，不扫描或复制整个文件，不新增依赖。支持 AES-128/192/256、UTF-8/GBK/GB18030/CP932/Shift-JIS/Big5，同样覆盖指定密码直接解压和无后缀嵌套 ZIP。

编码识别只改变指定密码的字节表达，不增加密码候选。两字节校验值不作为内容完整性证明，仍由实际解压和后续产物校验决定成功；无匹配、歧义或无效头部不缓存识别结果。Windows 保持原生命令行密码处理。

回归：`backend/tests/test_zip_aes_password_encoding.py`。
