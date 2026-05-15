import { MemoryViewer } from "../components/MemoryViewer";

export default function MemoryPage() {
  return (
    <section>
      <h2 className="mb-4 text-lg font-semibold">Memory</h2>
      <MemoryViewer />
    </section>
  );
}
