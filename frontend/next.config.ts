import type { NextConfig } from 'next';

const config: NextConfig = {
  poweredByHeader: false,
  allowedDevOrigins: ['localhost', '127.0.0.1'],
  ...(process.env.NODE_ENV === 'production'
    ? { output: 'export' as const }
    : {
        rewrites: async () => [
          {
            source: '/api/:path*',
            destination: 'http://localhost:8000/api/:path*',
          },
        ],
      }),
};

export default config;
