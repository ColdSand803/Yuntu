interface PageContainerProps {
  children: React.ReactNode;
}

export function PageContainer({ children }: PageContainerProps) {
  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      {children}
    </main>
  );
}
