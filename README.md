# QFNU 图书馆工具

`qfnu_login.py` 提供统一身份认证登录、CAS 换取图书馆令牌，以及图书馆区域、时段、座位和当前预约查询。
预约、取消、签到、签退属于真实写操作，必须显式添加 `--confirm` 才会发送请求。

## 安装依赖

```powershell
py -m pip install -r E:\fastApl\qfnu\_library\requirements.txt
```

## 使用

直接运行会提示输入账号和密码，密码不会写入源码：

```powershell
py E:\fastApl\qfnu\_library\qfnu_login.py
```

列出区域：

```powershell
py E:\fastApl\qfnu\_library\qfnu_login.py --action classrooms
```

查询明天的时段和空闲座位：

```powershell
py E:\fastApl\qfnu\_library\qfnu_login.py --action segments --classroom "西校区图书馆-三层自习室" --date tomorrow
py E:\fastApl\qfnu\_library\qfnu_login.py --action seats --classroom "西校区图书馆-三层自习室" --date tomorrow
```

查询当前预约：

```powershell
py E:\fastApl\qfnu\_library\qfnu_login.py --action reservations
```

写操作示例（请先确认参数和学校规定）：

```powershell
py E:\fastApl\qfnu\_library\qfnu_login.py --action reserve --classroom "西校区图书馆-三层自习室" --seat-id 1234 --segment 1 --confirm
py E:\fastApl\qfnu\_library\qfnu_login.py --action cancel --reservation-id 1234 --confirm
py E:\fastApl\qfnu\_library\qfnu_login.py --action check-out --confirm
```

签到功能在参考项目中被标记为可能违反图书馆规定，脚本不会自动执行；如确有授权，仍需手动添加 `--confirm`。

接口字段和区域映射参考 `qfnu-library-book`（CC BY-NC 4.0）。

## Vue 3 界面

项目同时包含一个 Vue 3 + Vite 的座位管理界面，入口为 `src/App.vue`，视觉风格参考 Apple 官网的留白、层级和克制配色。当前界面使用本地演示数据，已包含：

- 座位总览和可用率统计
- 校区/自习室、日期及时段切换
- 座位地图与状态筛选
- 选座、预约确认、预约列表和取消预约交互
- 统一认证登录弹窗与会话状态展示

启动前端开发服务器：

```powershell
cd E:\fastApl\qfnu\_library
npm install
npm run dev
```

然后访问 `http://127.0.0.1:5173/`。手机和同一局域网设备可访问电脑的局域网地址，例如 `http://10.180.73.18:5173/`。

预约确认、取消预约、查询预约、签到和签退都会通过 `api_server.py` 转发到图书馆真实接口。服务重启后登录会话会清空，需要在网页中重新登录；不会把账号密码写入磁盘。
