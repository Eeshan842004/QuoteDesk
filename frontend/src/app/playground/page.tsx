import { Suspense } from "react";
import { Playground } from "@/components/playground/playground";

export const metadata = { title: "Playground · QuoteDesk" };

export default function Page() {
  return (
    <Suspense>
      <Playground />
    </Suspense>
  );
}
