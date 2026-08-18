import { Skeleton, SkeletonHeading, SkeletonText } from "./Skeleton";

function PlaceItemSkeleton() {
  return (
    <div className="flex gap-4 rounded-2xl bg-white p-4">
      <Skeleton className="h-10 w-10 shrink-0 rounded-full" />
      <div className="flex-1 space-y-2">
        <SkeletonHeading className="w-2/5" />
        <SkeletonText className="w-full" />
        <SkeletonText className="w-3/4" />
      </div>
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="mx-auto max-w-6xl animate-fade-in" aria-label="加载中">
      <div className="mb-6 space-y-2">
        <Skeleton className="h-5 w-24 rounded-lg" />
        <SkeletonHeading className="w-56" />
        <SkeletonText className="w-80" />
      </div>

      <div className="mb-5 flex gap-2">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-10 w-20 rounded-xl" />
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <div className="space-y-3">
          <PlaceItemSkeleton />
          <PlaceItemSkeleton />
          <PlaceItemSkeleton />
          <PlaceItemSkeleton />
        </div>
        <Skeleton className="hidden h-80 rounded-2xl lg:block" />
      </div>
    </div>
  );
}
