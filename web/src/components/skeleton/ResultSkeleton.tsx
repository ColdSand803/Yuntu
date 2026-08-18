import { Skeleton, SkeletonHeading, SkeletonText } from "./Skeleton";

function CardSkeleton() {
  return (
    <div className="card space-y-4 p-6">
      <SkeletonHeading className="w-3/5" />
      <SkeletonText className="w-full" />
      <SkeletonText className="w-4/5" />
      <div className="flex gap-2 pt-2">
        <Skeleton className="h-6 w-16 rounded-full" />
        <Skeleton className="h-6 w-20 rounded-full" />
        <Skeleton className="h-6 w-14 rounded-full" />
      </div>
    </div>
  );
}

export function ResultSkeleton() {
  return (
    <div className="mx-auto max-w-4xl animate-fade-in" aria-label="加载中">
      <div className="mb-8 space-y-3 text-center">
        <SkeletonHeading className="mx-auto w-48" />
        <SkeletonText className="mx-auto w-64" />
      </div>
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        <CardSkeleton />
        <CardSkeleton />
        <CardSkeleton />
      </div>
    </div>
  );
}
