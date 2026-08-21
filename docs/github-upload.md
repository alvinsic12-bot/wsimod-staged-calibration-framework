# 上传至 GitHub（private repository）

本目录已经完成 `git init`、切换至 `main` 分支并暂存所有复现文件。首次提交需要先在本机设置你的 Git 身份；请在仓库根目录打开 PowerShell 后依次执行。

## 1. 设置本仓库的提交身份

将下列内容替换为你的 GitHub 显示名称与 GitHub 账户邮箱（或 GitHub 的 noreply 邮箱）：

```powershell
git config user.name "你的 GitHub 名称"
git config user.email "你的 GitHub 邮箱"
git commit -m "Initial reproducible WSIMOD staged calibration framework"
```

这两条 `git config` 命令不改动电脑上的全局设置，只应用于当前仓库。

## 2. 在 GitHub 网站创建私有仓库

1. 登录 [GitHub](https://github.com)，点击右上角 **+** → **New repository**。
2. Repository name 填入 `wsimod-staged-calibration-framework`。
3. 选择 **Private**。
4. 不要勾选 README、`.gitignore` 或 License（本地仓库已有这些文件）。
5. 点击 **Create repository**。

## 3. 连接并推送

GitHub 创建完成后，把下面的 `<YOUR-ACCOUNT>` 替换为你的 GitHub 用户名：

```powershell
git remote add origin https://github.com/<YOUR-ACCOUNT>/wsimod-staged-calibration-framework.git
git push -u origin main
```

首次推送时，Git Credential Manager 通常会打开浏览器要求登录 GitHub；完成授权即可。不要把 Personal Access Token 写入 notebook、README、命令历史或任何被 Git 跟踪的文件。

## 4. 推送后检查

```powershell
git status
python scripts/verify_inputs.py
```

预期 `git status` 显示 working tree clean，而输入验证显示 `Verified 2875 input files.`。GitHub 网页中应可看到 notebook、输入数据、`data_manifest.csv`、环境文件和文档；运行产生的 `wsimod-staged-calibration-framework_outputs/` 不会被提交。

## 5. 分享给导师或合作者

在 GitHub 仓库 **Settings** → **Collaborators** 中添加对方账户。对方克隆后执行：

```powershell
git clone https://github.com/<YOUR-ACCOUNT>/wsimod-staged-calibration-framework.git
cd wsimod-staged-calibration-framework
conda env create -f environment.yml
conda activate wsimod-staged-calibration-framework
python scripts/verify_inputs.py
jupyter lab
```

然后从 `notebooks/wsimod-staged-calibration-framework.ipynb` 顶部开始运行。
