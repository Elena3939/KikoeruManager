# 7-Zip 配置说明

Prekikoeru 的解压能力依赖 7-Zip。无论是普通压缩包、分卷压缩包还是部分异常后缀场景，都建议先把 7-Zip 配好。

## 1. 对应配置项

配置模型位于：

[settings.py](D:/Clash%20Verge/KikoeruTool_Elena/backend/app/config/settings.py)

对应字段：

```yaml
extract:
  seven_zip_path: "7z"
```

## 2. Windows 推荐配置

### 如果已经加入 PATH

直接使用：

```yaml
extract:
  seven_zip_path: "7z"
```

### 如果没有加入 PATH

填写完整路径，例如：

```yaml
extract:
  seven_zip_path: "C:\\Program Files\\7-Zip\\7z.exe"
```

## 3. Docker / Linux

Dockerfile 已安装 `p7zip-full`，一般保持默认即可：

```yaml
extract:
  seven_zip_path: "7z"
```

## 4. 如何验证是否可用

Windows：

```bat
where 7z
```

Linux：

```bash
which 7z
```

也可以直接执行：

```bash
7z
```

如果能输出帮助信息，就说明命令可用。

## 5. 常见问题

### 找不到 7z

- 确认已安装 7-Zip
- 确认路径填写的是 `7z.exe`
- 确认路径中没有拼写错误

### 保存配置后仍然报错

- 检查运行时实际读取的是哪份配置文件
- 手动调用一次配置重载
- 查看 `data/app.log`

### Docker 里还需要单独安装吗

通常不需要，仓库 Dockerfile 已处理。

## 6. 建议

- Windows 用户优先使用绝对路径，排除 PATH 差异
- 批量处理前，先用一个小压缩包验证解压链路
