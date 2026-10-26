# 08 · 找后端地址，不扫端口

## 为什么需要这一页

MCP 壳和业务后端是两个服务。壳的地址写进客户端配置就够了，但上传图纸、导出工艺卡要直连后端，于是每个新接入的人都要回答同一个问题：后端在哪。

试过的办法是扫端口。结果是找到 <backend-port> 之前先撞上三个无关服务——一个招采系统、一个前端应用、一个 Hello World。既慢，又容易把别人的服务当成目标。这样做还有一个更坏的后果：在有安全审计的网段里，端口扫描本身就会触发告警。

**扫端口不是发现机制，是没有发现机制时的替代品。**

## 反过来：只拿到后端，壳在哪

新人最常卡在这里——手上有后端地址，就把它的端口当 MCP 地址填进客户端，`POST /mcp` 返回 404，然后开始猜端口。壳和后端是**两个进程、两个端口**，后端的端口永远不是 MCP 端点。

按这个顺序找壳：

1. **问部署方要「MCP 端点」**，明确说是 `/mcp` 那个地址，不是后端地址。一句话就能答，比猜快。
2. **看本机接入单**：`~/.config/craft-process/endpoints.json` 里的 `mcp` 字段。
3. **有主机登录权限时直接看监听**：`ss -tlnp | grep -E 'python|uvicorn'`，或容器部署 `docker ps` 看端口映射。壳是 FastAPI/uvicorn，后端的 `/health` 在它自己的端口上，两者进程名不同。
4. **验一个候选端口，而不是看它开不开**：向 `http://<host>:<port>/mcp` 发 `initialize`，判据是 `200` + `mcp-session-id` 头 + body 有 `serverInfo`。壳上 `/health` 常常是 404，**404 不代表不是壳**；端口开着也不代表是壳。

不要扫网段、不要遍历端口。文档里出现过的 404 不是噪声，是信号：Flask/Werkzeug 风格的 404 页面说明那是后端，不是壳。

## 按顺序试这四条

**1. 环境变量。** `CRAFT_BACKEND_URL` 如果已设置，直接用。

**2. 本机配置。** `LOCAL.endpoints.md`、`~/.config/craft-process/endpoints.json`，或部署方给你的接入单。这一条只对配过的人有效。

接入单就两个键，一次配好，以后所有客户端都读它：

```json
{"mcp": "http://<mcp-host>:<mcp-port>/mcp",
 "backend": "http://<backend-host>:<backend-port>"}
```

**3. 问壳。** `craft_health` 目前只返回服务名和状态，不返回后端地址。打上 [patch 10](../patches/10-backend-address-discovery.md) 之后它会带上 `backend_url`，这是最省事的路径：知道 MCP 地址的人自动知道后端地址。

**4. 用脚本验证一个短名单。** 不是扫，是验证：

```bash
python tools/craft_discover.py --mcp http://<mcp-host>:<mcp-port>/mcp
# 默认只试同主机的 <backend-port>，可以用 --ports 追加已知候选
```

脚本做三件事：调 `craft_health` 拿到服务名（例如 `dica-2d-feature-extraction`），对候选地址请求 `/health`，只有返回的 `service` 与壳报告的一致才认可。端口开着但服务不对，会被明确列成 `skip` 而不是误认。

输出示例：

```
MCP shell : http://<mcp-host>:<mcp-port>/mcp
service   : dica-2d-feature-extraction
  skip    : http://<mcp-host>:5000 -> HTTP 404
backend   : http://<mcp-host>:<backend-port>  [verified via host + port <backend-port>; /health service matches]
```

## 验证标准

一个候选地址算「找到了」，必须同时满足：

`/health` 返回 JSON；其中的 `service` 等于 `craft_health` 报告的服务名；随后 `/api/jobs` 对该地址有响应（GET 405 或 POST 可接受都算，说明路由存在）。

只满足「端口通」不算。这是当初误撞三个服务的原因。

## 找不到怎么办

停下来问部署方，不要扩大端口范围。把这三样发给对方，通常一句话就能答：MCP 地址、`craft_health` 返回的服务名、你要做的操作（上传图纸还是导出工艺卡）。

如果对方也说不清，让他看壳的启动配置里那个 `CRAFT_API_BASE_URL` 之类的环境变量——壳自己一定知道答案，只是现在没有把它说出来。
