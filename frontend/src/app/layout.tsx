import type { Metadata } from 'next';
import '../styles.css';

export const metadata: Metadata = {
  title: 'Taskroom · AI Task Bot',
  description: 'Your private taskroom for text and voice tasks.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
