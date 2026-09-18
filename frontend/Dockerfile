# 阶段1: 构建前端
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
ENV NODE_OPTIONS=--max-old-space-size=1024
RUN npm run build

# 阶段2: Nginx 托管静态文件
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# nginx:alpine 自带的 10-listen-on-ipv6-by-default.sh 会调用 `apk manifest nginx`，
# 在部分宿主机上会无限期挂住，导致 nginx 主进程不启动（表现为 8080 连接被重置、
# 外层网关 502）。该脚本仅用于追加 IPv6 监听，我们统一走 IPv4，故移除。
RUN rm -f /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
