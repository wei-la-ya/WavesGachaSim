# 🌊 WavesGachaSim 鸣潮模拟抽卡插件

<p align="center">
  <img src="https://img.shields.io/badge/Version-1.1.0-blue?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/License-GPL--3.0-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Python-3.10+-orange?style=flat-square" alt="Python">
</p>

> 基于 gsuid_core 框架的鸣潮（Wuthering Waves）模拟抽卡插件，原生支持图片渲染、保底机制、特征码系统！

## ✨ 功能特性

- 🎰 **限定角色/武器池十连抽** - 模拟官方卡池，支持当期 UP 角色
- 🎯 **常驻角色/武器池** - 经典唤取模拟
- 🛡️ **保底机制** - 完整还原鸣潮保底规则（5星 80 抽、4星 10 抽）
- 💫 **50/50 歪卡机制** - 限定角色池经典体验
- 📊 **保底状态查询** - 随时查看各池保底进度
- 📈 **出货统计** - 记录你的 5 星出货历史
- 🔢 **特征码系统** - 9 位数字用户标识，绑定抽卡记录
- 📅 **每日抽卡限制** - 可配置的每日抽卡上限
- 🖼️ **精美图片渲染** - 支持本地/远程渲染，失败自动回退文本
- 🔄 **卡池自动更新** - 每日自动从 API 获取最新卡池

## 📋 命令列表

| 命令 | 功能说明 |
|------|----------|
| `ww抽卡` | 限定角色十连抽 |
| `ww抽卡武器` | 限定武器十连抽 |
| `ww抽卡常驻` | 常驻角色十连抽 |
| `ww抽卡常驻武器` | 常驻武器十连抽 |
| `ww切换卡池` | 切换限定池（输入编号或名称） |
| `ww卡池状态` | 查看当前保底状态 |
| `ww抽卡统计` | 查看 5 星历史记录 |
| `ww抽卡概率` | 查看概率说明 |
| `ww更新卡池` | 强制从 API 刷新卡池 |
| `ww模拟绑定` | 绑定/查看特征码 |
| `ww抽卡帮助` | 查看帮助信息 |

## 📦 安装方法

```bash
# 在 gsuid_core 插件目录执行
git clone https://github.com/wei-la-ya/WavesGachaSim.git
```

## ⚙️ 配置说明

插件提供以下配置项（可在 Web 管理后台修改）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `GachaSimEnabled` | ✅ 开启 | 模拟抽卡总开关 |
| `GachaSimDailyLimit` | 300 | 每日抽卡次数上限 |
| `GachaSimMasterUnlimited` | ✅ 开启 | 主人无限抽取 |
| `GachaSimTextFallback` | ✅ 开启 | 渲染失败时使用文本 |
| `GachaSimRemoteRenderEnable` | ❌ 关闭 | 外置渲染开关 |
| `GachaSimRemoteRenderUrl` | http://127.0.0.1:3000/render | 外置渲染地址 |
| `GachaSimPoolMode` | 跟随接口 | 卡池选择模式 |
| `GachaSimUserSwitchAll` | ✅ 开启 | 用户可切换全部卡池 |

## 📂 项目结构

```
WavesGachaSim/
├── __init__.py                 # 插件入口
├── pyproject.toml              # 项目配置
├── README.md                   # 用户文档
├── ICON.png                    # 插件图标
└── WavesGachaSim/
    ├── __init__.py             # 命令处理逻辑
    ├── gacha_service.py       # 抽卡核心算法
    ├── pool_manager.py        # 卡池管理
    ├── data_manager.py        # 数据层封装
    ├── models.py              # 数据库模型
    ├── api.py                 # API 请求
    ├── draw_gacha_result.py   # 图片渲染
    ├── gacha_sim_config.py    # 配置项
    ├── gacha_help/
    │   ├── help.json          # 帮助信息
    │   └── get_help.py        # 帮助图生成
    ├── config/
    │   ├── standard_pools.json # 常驻池配置
    │   └── weapons_3star.json # 3星武器列表
    ├── templates/              # HTML 模板
    └── texture2d/             # 图片素材
```


## 🤝 致谢

- [gsuid_core](https://github.com/gsuid_core/gsuid_core) - 核心框架
- [XutheringWavesUID](https://github.com/Loping151/XutheringWavesUID) - 资源图片与卡池数据来源
- [AstrBot鸣潮模拟抽卡插件](https://github.com/Ruafafa/astrbot_plugin_ww_gacha_sim) - 部分样式与资源参考使用来源
- **Claude**
- **Gemini**
- **ChatGPT**
- **Minimax**
- **豆包**
- **DeepSeek**
- **Kimi**

## 📄 License

本插件基于 **GPL-3.0-or-later** 许可证开源。

---

<p align="center">
  <sub>Made with ❤️ for Wuthering Waves players</sub>
</p>
