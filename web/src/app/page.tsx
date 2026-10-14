// Operator entry point (QA-013): mounts the wired operator app, which renders
// OperatorShell with the runtime capability provider and the real ApiClient.
import { OperatorApp } from "@/components/OperatorApp";

export default function Home() {
  return (
    <>
      <h1 className="sr-only">blackRabbit Operator</h1>
      <OperatorApp />
    </>
  );
}
