import { useEffect, useId, useRef, type ReactNode } from "react";
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
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    ref.current?.showModal();
    return () => ref.current?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      onCancel={close}
      className="modal"
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
    >
      <div className="modal-head">
        <div className="modal-heading">
          <h2 id={titleId}>{title}</h2>
          {description && (
            <p id={descriptionId} className="modal-description">
              {description}
            </p>
          )}
        </div>
        <Button aria-label="关闭" onClick={close} variant="ghost">
          <X size={18} />
        </Button>
      </div>
      <div className="modal-body">{children}</div>
    </dialog>
  );
}
