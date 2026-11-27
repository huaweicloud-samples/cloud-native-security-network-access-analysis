# 部署指导 — VPC 网络访问分析自动化（华为云）

## 1. 前置条件

- 已注册华为云账号并完成实名认证，余额充足，区域配额充足。
- 本地安装：Terraform（>= 1.0）、Python（>= 3.9）、`zip`、`python3 -m pip`。
- 配置凭据（**切勿写入任何文件**）：在部署机导出环境变量
```bash
export HW_ACCESS_KEY="<你的AK>"
export HW_SECRET_KEY="<你的SK>"
# 仅当使用临时凭证时：export HW_SECURITY_TOKEN="<你的Token>"
export HW_REGION_NAME="cn-north-4"
```
- 访问密钥配置方式（二选一，默认为 AK/SK 环境变量）：
- **方式 A（推荐，无长期密钥）**：`create_agency = true`，由 Terraform 创建 IAM 委托并委托给 FunctionGraph，函数运行时由 FunctionGraph 注入临时凭据。**前提**：部署所用的 IAM 用户需具备委托信任权限。若账号下该用户无此权限，FunctionGraph 会返回 `FSS.1501 "The agency does not exist"`（委托在 IAM 已存在但 FunctionGraph 无法解析），此时改用方式 B。
- **方式 B（AK/SK 注入，默认）**：`create_agency = false`（默认），函数从自身环境变量 `HW_ACCESS_KEY` / `HW_SECRET_KEY`（由 Terraform 经 `user_data` 注入）读取长期密钥。代码层 `src/shared/huawei_clients.py` 已同时支持两种方式（`context` 优先，回退到环境变量）。
- 无论哪种方式，密钥**绝不以明文落盘到交付文件**；方式 B 的密钥仅经 `terraform apply -var=...` 注入，留存于 state（建议部署后轮换）。
- **project_id（必填，非密钥）**：华为云 `BasicCredentials` 的第三参数必须是项目 UUID，填区域名（如 `cn-north-4`）会触发 `401 get token error`。变量 `project_id` 已默认填好本账号 cn-north-4 的项目 UUID；换账号请改为目标账号对应项目 id（控制台「我的凭证 → 项目 ID」或 `openstack project list`）。
- （可选）SMN 通知：Topic 由 Terraform 自动创建，部署后订阅即可。SecMaster 已停用，无需创建工作空间。

## 2. 构建函数包

```bash
cd infra
python3 ../scripts/build_packages.py
```

该脚本在 `infra/build/` 下产出 `run_analysis.zip`、`check_analysis.zip`、`send_findings.zip`。**每个函数包自带华为云 SDK，自包含**，内含 `app.py` + `src/engine` + `src/shared` + `src/scopes` + SDK 包（`huaweicloudsdkcore` / `vpc` / `smn` / `secmaster`）。

> **SDK 打包策略（关键）**：FunctionGraph Python 运行时（实测 `3.9.2`）预装了 `huaweicloudsdkcore` 与 `huaweicloudsdksmn`，但**未预装** `huaweicloudsdkvpc` 与 `huaweicloudsdksecmaster`。因此 `build_packages.py` 用 **manylinux2014_x86_64 / py39 轮子**安装这四个 SDK 并打进每个 zip（即便在 Windows 上构建，也强制拉取 Linux 兼容轮子，否则 Windows 的 `.pyd` 无法在 Linux 运行时加载）。**不要**再单独用 `huaweicloud_fgs_dependency` 依赖层——该层在本账号上会触发 `FSS.1056 "dependency does not exist"` 的 id/异步发布不一致问题，已弃用。

> 打包已过滤 `__pycache__`，避免空包导致运行时静默崩溃。

> **代码更新必读（FunctionGraph 拉取陷阱）**：FunctionGraph **原地更新函数不会可靠地从 OBS 重新拉取代码**，只有「新建」才会。`infra/main.tf` 已通过给每个 `huaweicloud_fgs_function` 加 `lifecycle { replace_triggered_by = [huaweicloud_obs_bucket_object.<fn>] }` 解决：OBS 对象 etag 一变（即代码包内容变化），函数会被**自动重建**并拉取新代码。此外 `user_data` 里塞了 `CODE_ETAG` 作为二次保险。所以**改完代码后只需** `python3 ../scripts/build_packages.py && terraform apply` 即可，函数会自动重建拿到新代码。

## 3. 初始化并预览

```bash
cd infra
terraform init
terraform plan
```

`terraform plan` 不收费。默认（`create_agency=false`）将创建：OBS 桶 ×1、fgs 函数 ×3、TIMER 触发器 ×1、LTS 日志组/流 ×1、SMN Topic ×1（SDK 已打进函数包，无独立 fgs 依赖层）；IAM 委托仅在 `create_agency=true` 时出现。

## 4. 资源确认（apply 前必读）

> 本实践使用的云服务规格以华为云控制台实际展示为准；执行 `terraform plan` 可预览将创建的资源清单。

## 5. 应用

默认走 **方式 B（AK/SK 注入）**，需把部署机环境变量里的 AK/SK 透传进 `apply`（`hw_access_key` / `hw_secret_key` 为 `sensitive` 变量，不会回显到计划/状态输出明文以外；**切勿写入 `terraform.tfvars`**）：

```bash
terraform apply \
-var="hw_access_key=$HW_ACCESS_KEY" \
-var="hw_secret_key=$HW_SECRET_KEY"
```

若改用方式 A（无密钥委托），追加 `-var="create_agency=true"`（需部署用户具备委托信任权限，否则会遇 FSS.1501，见上文）。

其它常用变量：`region`、`schedule_expression`（默认 `12h`）、`smn_topic_name`、`project_id`（默认已填本账号 cn-north-4 项目 UUID，换账号必改）。

> 提示：AK/SK 会进入 `terraform.tfstate`（明文）。部署完成后建议在控制台轮换该密钥对，使 state 中旧值失效。

部署成功后，`run_analysis` 函数即被 TIMER 触发器每 12 小时调用一次。

## 6. 配置 Scope（可选）

默认 `src/scopes/` 含 3 个示例 Scope：互联网出向、互联网入向端口、跨 VPC。修改或新增 Scope 后，重新执行 `scripts/package.sh` 并 `terraform apply` 重新部署对应函数即可。

> `all_vpc_egress_to_port.json` 中的 `REPLACE_VPC_A_ID` / `REPLACE_VPC_B_ID` 需替换为真实 VPC ID。

## 7. 验证

1. 在 FunctionGraph 控制台手动「测试」`run_analysis`，观察返回 JSON 的 `total_findings` 与 `sink` 字段。
2. 查看 LTS 日志流 `vpcaa-stream`，检索 `NETWORK_ACCESS_FINDINGS` 结构化日志。
3. 若配置了 SMN，检查订阅终端是否收到通知。SecMaster 已停用，无需查看。
4. 确认 TIMER 触发器状态为 `ACTIVE`，下次触发时间符合预期。

## 8. 清理

```bash
terraform destroy
```

`terraform destroy` 仅删除本 state 内资源（OBS 桶已设 `force_destroy`）。销毁后建议在控制台确认无残留（OBS / LTS / SMN Topic）。
