"use client";

import { useRef, useState } from "react";

export interface ImageAttachment {
  filename: string;
  mimeType: string;
  data: string; // base64, no data: prefix
}

const MAX_IMAGE_BYTES = 4 * 1024 * 1024;

function readImage(file: File): Promise<ImageAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ filename: file.name, mimeType: file.type, data: String(reader.result).split(",")[1] || "" });
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function Composer({
  disabled,
  busy,
  waitingForDecision = false,
  canStop,
  onSend,
  onStop,
}: {
  disabled: boolean;
  busy: boolean;
  waitingForDecision?: boolean;
  canStop: boolean;
  onSend: (text: string, images: ImageAttachment[]) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");
  const [images, setImages] = useState<ImageAttachment[]>([]);
  const [notice, setNotice] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const canSend = !disabled && !busy && text.trim().length > 0;

  const submit = () => {
    if (!canSend) return;
    onSend(text.trim(), images);
    setText("");
    setImages([]);
    setNotice("");
    if (areaRef.current) areaRef.current.style.height = "auto";
  };

  const pick = async (files: FileList | null) => {
    if (!files) return;
    const accepted: ImageAttachment[] = [];
    for (const f of Array.from(files)) {
      if (!f.type.startsWith("image/")) {
        setNotice(`${f.name} was skipped: only images can be sent to the agent.`);
        continue;
      }
      if (f.size > MAX_IMAGE_BYTES) {
        setNotice(`${f.name} was skipped: images must be under 4 MB.`);
        continue;
      }
      accepted.push(await readImage(f));
    }
    setImages((prev) => [...prev, ...accepted]);
  };

  return (
    <div className="px-3 sm:px-4 pb-4 sm:pb-5 pt-2">
      <div className="max-w-4xl mx-auto">
        {(images.length > 0 || notice) && (
          <div className="flex flex-wrap items-center gap-2 px-1 pb-2">
            {images.map((img, i) => (
              <span key={`${img.filename}-${i}`} className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs bg-surface border border-border-soft rounded-lg">
                <span className="font-medium text-text max-w-[180px] truncate">{img.filename}</span>
                <button
                  type="button"
                  aria-label={`Remove ${img.filename}`}
                  onClick={() => setImages((prev) => prev.filter((_, j) => j !== i))}
                  className="text-muted hover:text-red-500 transition-colors"
                >
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </span>
            ))}
            {notice && <span className="text-xs text-muted">{notice}</span>}
          </div>
        )}
        <div className="flex items-end gap-2 bg-surface rounded-2xl border border-border-soft px-3 py-2 focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--accent-soft),0_4px_16px_rgba(0,0,0,0.04)] shadow-lg transition-all duration-200">
          <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => { void pick(e.target.files); e.target.value = ""; }} />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={disabled || busy}
            title="Attach images"
            aria-label="Attach images"
            className="p-2 text-muted hover:text-accent rounded-lg hover:bg-hover transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" />
            </svg>
          </button>
          <textarea
            ref={areaRef}
            value={text}
            data-testid="message-input"
            aria-label="Message"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            onInput={(e) => {
              const t = e.currentTarget;
              t.style.height = "auto";
              t.style.height = `${Math.min(t.scrollHeight, 200)}px`;
            }}
            placeholder={
              waitingForDecision
                ? "Answer the agent's question to continue…"
                : busy
                  ? "The agent is working…"
                  : "Ask me anything…"
            }
            rows={1}
            disabled={disabled}
            className="flex-1 resize-none text-sm text-text placeholder:text-muted bg-transparent border-none focus:outline-none focus:ring-0 py-2 px-1 disabled:opacity-50"
            style={{ minHeight: "36px", maxHeight: "200px" }}
          />
          {busy && canStop ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop the agent"
              data-testid="stop-button"
              className="p-2.5 bg-surface-2 text-text rounded-xl border border-border-soft hover:bg-hover transition-all duration-200"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!canSend}
              aria-label="Send message"
              data-testid="send-button"
              className="p-2.5 bg-accent text-accent-fg rounded-xl transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed shadow-md hover:shadow-lg active:scale-95"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
