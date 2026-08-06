import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');

  // 解析 allowedHosts（支持逗号分隔域名，支持 * 全局放行）
  const rawHosts = env.VITE_ALLOWED_HOSTS || '';
  let allowedHosts;
  if (rawHosts === '*') {
    allowedHosts = true; // vite标准：true / "all" 代表允许所有host
  } else {
    const hosts = rawHosts
      .split(',')
      .map(h => h.trim())
      .filter(Boolean);
    allowedHosts = hosts.includes('*') ? true : hosts;
  }

  return {
    server: {
      host: env.VITE_HOST || '0.0.0.0',
      port: parseInt(env.VITE_PORT) || 5173,
      // 正确赋值：不需要判断length，直接使用解析后的变量
      allowedHosts,
      proxy: {
        '/api': {
          target: env.VITE_API_TARGET || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
    },
  };
});