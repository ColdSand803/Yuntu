interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className = "" }: SkeletonProps) {
  return (
    <div
      className={`animate-skeleton rounded-xl bg-primary-100/60 ${className}`}
      aria-hidden="true"
    />
  );
}

export function SkeletonText({ className = "" }: SkeletonProps) {
  return <Skeleton className={`h-4 ${className}`} />;
}

export function SkeletonHeading({ className = "" }: SkeletonProps) {
  return <Skeleton className={`h-7 ${className}`} />;
}
