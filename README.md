# QFNU 图书馆工具

这是一个面向曲阜师范大学图书馆的 Vue 3 + FastAPI 工具，支持统一身份认证、实时座位查询、真实预约和可选的自动预约/签到/签退任务。

## 功能

- IDS 统一身份认证登录，并通过 CAS 获取图书馆会话令牌
- 自动处理登录流程中的滑块验证
- 查询 19 个图书馆空间、明日时段和完整座位状态
- 座位地图支持全部、仅空闲、已预约、使用中筛选
- 真实预约、取消预约、签到和签退
- 定时预约明日座位
- 定时自动签到和签退
- 一次性执行或每天重复执行
- 任务配置保存到 `automation_config.json`，不保存账号密码
- 图书馆会话失效时，自动使用本次登录凭据重新登录并将原操作重试一次
- Vue 3 移动端适配，支持局域网手机访问
- Apple 风格的地点选择器、时间滚轮和应用内确认弹窗

## 安装依赖

```powershell
py -m pip install -r E:\fastApl\qfnu\_library\requirements.txt
cd E:\fastApl\qfnu\_library
npm install
```

## 启动服务

需要同时启动后端和前端，后端必须保持运行，定时任务才能触发。

终端一：

```powershell
cd E:\fastApl\qfnu\_library
py -m uvicorn api_server:app --host 0.0.0.0 --port 8000
```

终端二：

```powershell
cd E:\fastApl\qfnu\_library
npm run dev -- --host 0.0.0.0
```

访问地址：

- 电脑访问：`http://127.0.0.1:5173/`
- 局域网手机访问：`http://电脑局域网IP:5173/`

例如：`http://10.180.73.18:5173/`

## 命令行使用

直接运行会提示输入账号和密码，凭据不会写入源码：

```powershell
py E:\fastApl\qfnu\_library\qfnu_login.py
```

查询空间：

```powershell
py E:\fastApl\qfnu\_library\qfnu_login.py --action classrooms
```

查询明日时段和空闲座位：

```powershell
py E:\fastApl\qfnu\_library\qfnu_login.py --action segments --classroom "西校区图书馆-三层自习室" --date tomorrow
py E:\fastApl\qfnu\_library\qfnu_login.py --action seats --classroom "西校区图书馆-三层自习室" --date tomorrow
```

查询预约记录：

```powershell
py E:\fastApl\qfnu\_library\qfnu_login.py --action reservations
```

真实写操作示例：

```powershell
py E:\fastApl\qfnu\_library\qfnu_login.py --action reserve --classroom "西校区图书馆-三层自习室" --seat-id 1234 --segment 1836225 --confirm
py E:\fastApl\qfnu\_library\qfnu_login.py --action cancel --reservation-id 1234 --confirm
py E:\fastApl\qfnu\_library\qfnu_login.py --action check-in --confirm
py E:\fastApl\qfnu\_library\qfnu_login.py --action check-out --confirm
```

`reserve`、`cancel`、`check-in` 和 `check-out` 会改变图书馆账号状态，必须显式添加 `--confirm`。请先确认学校规定允许相关操作。

## 定时任务

在网页的“自动执行”页面中配置：

1. 打开“启用定时任务”。
2. 打开“自动预约明日座位”。
3. 设置预约时间，例如 `19:20`。
4. 选择空间、明日真实时段和座位 ID。也可以先在座位地图选座，再点击“加入明日定时预约”。
5. 设置自动签到和签退时间。
6. 打开“每天重复执行”即可每天预约第二天同一座位。
7. 点击保存。

执行时后端会重新读取明日时段并校验座位状态，不会直接复用过期的 segment ID。关闭“每天重复执行”时，每个动作只执行一次。

服务重启后登录会话会清空，需要重新登录；任务配置会从 `automation_config.json` 恢复，但未登录时不会执行任何自动操作。

登录密码仅保存在后端进程内存中，不会写入文件或日志。后端运行期间如果图书馆会话过期，查询、预约、取消、签到、签退和定时任务会自动重新登录并重试一次；如果重新登录失败，接口会返回 401，需要在页面重新登录。服务重启后不会自动恢复凭据，仍需手动登录。

## 开发检查

```powershell
npm run build
py -m compileall -q api_server.py qfnu_login.py
```

接口和区域映射参考 `qfnu-library-book`（CC BY-NC 4.0）。
