# QFNU 图书馆工具

面向**曲阜师范大学**图书馆的 Web 工具，基于 Vue 3 + FastAPI，支持统一身份认证登录、实时座位查询、真实预约、自动签到/签退。

## 功能

- IDS 统一身份认证登录，自动处理滑块验证
- 查询图书馆空间、明日时段和完整座位状态
- 座位地图支持全部、仅空闲、已预约、使用中筛选
- 真实预约、取消预约、签到和签退
- 定时自动预约明日座位、自动签到和签退
- 一次性执行或每天重复执行
- 任务配置保存到 `automation_config.json`，不保存账号密码
- 图书馆会话失效时，自动重新登录并重试
- Vue 3 移动端适配，支持局域网手机访问

## 环境要求

- **Python** 3.9+
- **Node.js** 16+（推荐 18+）

## 下载项目

```bash
git clone https://github.com/hunaol/qfnu_library.git
cd qfnu_library
```

## 安装依赖

### Python 后端

```bash
pip install -r requirements.txt
```

依赖包：

| 包 | 用途 |
|---|---|
| `requests` | HTTP 请求 |
| `numpy` / `Pillow` / `opencv-python` | 滑块验证图像处理 |
| `cryptography` | 加密通信 |
| `fastapi` / `uvicorn` | Web API 服务 |

### 前端

```bash
npm install
```

依赖包：

| 包 | 用途 |
|---|---|
| `vue` | 前端框架 |
| `vite` | 构建工具 |
| `lucide-vue-next` | 图标库 |

## 启动服务

需要**同时启动后端和前端**，后端保持运行定时任务才能触发。

**终端一 — 启动后端（端口 8000）：**

```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

**终端二 — 启动前端（端口 5173）：**

```bash
npm run dev
```

访问地址：

| 设备 | 地址 |
|------|------|
| 电脑 | `http://127.0.0.1:5173` |
| 局域网手机 | `http://电脑IP:5173` |

> 前端通过 Vite 代理将 `/api` 请求转发到后端 `http://127.0.0.1:8000`。

## 命令行使用

不启动 Web 服务时，也可以直接通过命令行操作：

```bash
# 查询空间列表
python qfnu_login.py --action classrooms

# 查询明日时段
python qfnu_login.py --action segments --classroom "西校区图书馆-三层自习室" --date tomorrow

# 查询空闲座位
python qfnu_login.py --action seats --classroom "西校区图书馆-三层自习室" --date tomorrow

# 查询预约记录
python qfnu_login.py --action reservations

# 预约座位（需加 --confirm 确认）
python qfnu_login.py --action reserve --classroom "西校区图书馆-三层自习室" --seat-id 1234 --segment 1836225 --confirm

# 取消预约
python qfnu_login.py --action cancel --reservation-id 1234 --confirm

# 签到 / 签退
python qfnu_login.py --action check-in --confirm
python qfnu_login.py --action check-out --confirm
```

> `reserve`、`cancel`、`check-in`、`check-out` 会改变图书馆账号状态，必须加 `--confirm`。请先确认学校规定允许相关操作。

## 定时任务配置

在网页「自动执行」页面中：

1. 开启「启用定时任务」
2. 开启「自动预约明日座位」
3. 设置预约时间（如 `19:20`）
4. 选择空间、时段和座位（也可在座位地图选座后点「加入明日定时预约」）
5. 设置签到和签退时间
6. 开启「每天重复执行」即可每天自动预约第二天同一座位
7. 点击「保存自动执行设置」

服务重启后需重新登录，但任务配置会从 `automation_config.json` 恢复。

## 项目结构

```
qfnu_library/
├── api_server.py          # FastAPI 后端服务
├── qfnu_login.py          # 统一身份认证 & 图书馆 API 封装
├── index.html             # 前端入口
├── vite.config.js         # Vite 配置（代理 & 端口）
├── package.json           # 前端依赖
├── requirements.txt       # Python 依赖
├── automation_config.json # 定时任务配置（自动生成）
├── src/
│   ├── App.vue            # 主应用组件
│   ├── main.js            # Vue 入口
│   ├── style.css          # 全局样式
│   ├── TimeWheelPicker.vue    # 时间选择器
│   └── LocationPicker.vue     # 地点选择器
└── README.md
```

## 开发

```bash
# 构建前端
npm run build

# 检查 Python 语法
python -m compileall -q api_server.py qfnu_login.py
```

## 协议

接口和区域映射参考 `qfnu-library-book`（CC BY-NC 4.0）。
