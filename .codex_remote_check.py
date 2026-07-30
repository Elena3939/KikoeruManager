import os

import paramiko


client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(
    os.environ["KM_SSH_HOST"],
    username=os.environ["KM_SSH_USER"],
    password=os.environ["KM_SSH_PASSWORD"],
    timeout=15,
    auth_timeout=15,
    banner_timeout=15,
)

stdin, stdout, stderr = client.exec_command(
    os.environ["KM_REMOTE_COMMAND"],
    get_pty=True,
    timeout=120,
)
stdin.write(os.environ["KM_SSH_PASSWORD"] + "\n")
stdin.flush()

print(stdout.read().decode("utf-8", "replace"), end="")
print(stderr.read().decode("utf-8", "replace"), end="")
status = stdout.channel.recv_exit_status()
client.close()
raise SystemExit(status)
