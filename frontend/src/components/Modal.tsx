import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "./ui/button";
export function Modal({
  title,
  description,
  close,
  children,
}: {
  title: string;
  description?: string;
  close: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    return () => ref.current?.close();
  }, []);
  return (
    <dialog ref={ref} onCancel={close} className="modal" aria-label={title}>
      <div className="modal-head">
        <div>
          <h2>{title}</h2>
          {description && <p className="modal-description">{description}</p>}
        </div>
        <Button aria-label="关闭" onClick={close} variant="ghost">
          <X size={18} />
        </Button>
      </div>
      {children}
    </dialog>
  );
}
