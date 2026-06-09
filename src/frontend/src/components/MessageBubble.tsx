"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChatMessage, Attachment } from "@/types";

import { getApiUrl } from "@/lib/config";

/** Build the download-link prefix on demand so it picks up runtime config. */
function getDlPrefix(): string {
  return `${getApiUrl()}/api/files/download/`;
}

const IMAGE_EXTS = /\.(png|jpe?g|gif|webp|svg|bmp|ico)$/i;
const PDF_EXT = /\.pdf$/i;

/**
 * Detect absolute file paths (e.g. /tmp/foo.pdf) in agent responses and rewrite
 * them as markdown download links pointing at the backend file-serving endpoint.
 * Also strips surrounding backticks/bold markers so the link isn't rendered as code.
 */
function rewriteFilePaths(text: string): string {
  const dlPrefix = getDlPrefix();
  return text.replace(
    /`{0,3}\*{0,2}(\/tmp\/[\w.\-\/]+\.[a-zA-Z0-9]{1,10})\*{0,2}`{0,3}/g,
    (_match, path: string) => {
      const filename = path.split("/").pop() || path;
      const url = `${dlPrefix}${encodeURIComponent(filename)}?path=${encodeURIComponent(path)}`;
      // Use markdown image syntax for images so ReactMarkdown renders <img>
      if (IMAGE_EXTS.test(filename)) {
        return `![${filename}](${url}&inline=true)`;
      }
      return `[${filename}](${url})`;
    }
  );
}

/** Get a human-readable icon for a file extension */
function getFileIcon(name: string) {
  if (IMAGE_EXTS.test(name)) {
    return (
      <svg className="w-3.5 h-3.5 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.41a2.25 2.25 0 013.182 0l2.909 2.91m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
      </svg>
    );
  }
  if (PDF_EXT.test(name)) {
    return (
      <svg className="w-3.5 h-3.5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
      </svg>
    );
  }
  return (
    <svg className="w-3.5 h-3.5 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
    </svg>
  );
}

/** Renders attachment chips for user messages */
function AttachmentChips({ attachments }: { attachments: Attachment[] }) {
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {attachments.map((att, idx) => {
        const name = att.displayName || ("path" in att ? att.path : "file");
        return (
          <span
            key={idx}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs bg-surface rounded-lg"
          >
            {getFileIcon(name)}
            <span className="font-medium max-w-[180px] truncate">{name}</span>
          </span>
        );
      })}
    </div>
  );
}

/** Inline PDF preview with expand/collapse */
function PdfPreview({ href, filename }: { href: string; filename: string }) {
  const [expanded, setExpanded] = useState(false);
  const inlineUrl = href.includes("?") ? `${href}&inline=true` : `${href}?inline=true`;

  return (
    <div className="my-3 rounded-xl overflow-hidden border border-border-soft bg-surface-2">
      <div className="flex items-center justify-between px-3 py-2 bg-surface border-b border-border-soft">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <span className="text-sm font-medium text-text">{filename}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1.5 text-muted hover:text-text rounded-md hover:bg-hover transition-all"
            title={expanded ? "Collapse" : "Expand preview"}
          >
            <svg className={`w-4 h-4 transition-transform ${expanded ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
            </svg>
          </button>
          <a
            href={href}
            download={filename}
            rel="noopener noreferrer"
            className="p-1.5 text-muted hover:text-accent rounded-md hover:bg-hover transition-all"
            title="Download"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
            </svg>
          </a>
        </div>
      </div>
      {expanded && (
        <iframe
          src={inlineUrl}
          className="w-full border-0"
          style={{ height: "500px" }}
          title={filename}
        />
      )}
      {!expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="w-full py-6 flex flex-col items-center gap-2 text-muted hover:text-text transition-colors"
        >
          <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <span className="text-sm">Click to preview PDF</span>
        </button>
      )}
    </div>
  );
}

interface Props {
  message: ChatMessage;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const content = isUser ? message.content : rewriteFilePaths(message.content);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} animate-slide-up`}>
      {/* Assistant avatar */}
      {!isUser && (
        <div className="flex-shrink-0 mr-3 mt-1">
          <div className="w-8 h-8 rounded-xl bg-accent flex items-center justify-center shadow-lg ring-1 ring-white/10">
            <svg className="w-4 h-4 text-accent-fg drop-shadow-sm" viewBox="0 0 24 24" fill="currentColor">
              <path fillRule="evenodd" d="M14.615 1.595a.75.75 0 01.359.852L12.982 9.75h7.268a.75.75 0 01.548 1.262l-10.5 11.25a.75.75 0 01-1.272-.71l1.992-7.302H3.75a.75.75 0 01-.548-1.262l10.5-11.25a.75.75 0 01.913-.143z" clipRule="evenodd" />
            </svg>
          </div>
        </div>
      )}

      <div
        className={`max-w-[75%] ${
          isUser
            ? "rounded-2xl rounded-br-sm px-4 py-3 bg-gradient-to-br from-primary-600 to-violet-600 text-white shadow-md shadow-primary-500/20"
            : "rounded-2xl rounded-bl-sm px-4 py-3 bg-white dark:bg-navy-900/80 border border-slate-100 dark:border-white/[0.06] text-slate-800 dark:text-slate-200 shadow-sm shadow-slate-100/50 dark:shadow-black/10"
        }`}
      >
        {isUser ? (
          <>
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>
            {message.attachments && message.attachments.length > 0 && (
              <AttachmentChips attachments={message.attachments} />
            )}
          </>
        ) : (
          <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none prose-p:my-1.5 prose-li:my-0 prose-table:my-2 prose-th:px-3 prose-th:py-2 prose-td:px-3 prose-td:py-2 prose-th:text-left prose-th:bg-slate-50 dark:prose-th:bg-white/[0.04] prose-th:font-semibold prose-table:border-collapse prose-table:w-full prose-headings:text-slate-900 dark:prose-headings:text-white prose-a:text-primary-600 dark:prose-a:text-primary-400 prose-strong:text-slate-900 dark:prose-strong:text-white">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                img: ({ src, alt }) => {
                  if (!src) return null;
                  return (
                    <a href={src} target="_blank" rel="noopener noreferrer" className="block my-3">
                      <img
                        src={src}
                        alt={alt || ""}
                        className="max-w-full rounded-xl border border-border-soft shadow-sm hover:shadow-md transition-shadow cursor-pointer"
                        style={{ maxHeight: "400px" }}
                        loading="lazy"
                      />
                    </a>
                  );
                },
                a: ({ href, children }) => {
                  const prefix = getDlPrefix();
                  const isDownload = href?.startsWith(prefix);
                  if (isDownload && href) {
                    const urlFilename = decodeURIComponent(
                      href.slice(prefix.length).split("?")[0]
                    );

                    // PDF — render inline preview
                    if (PDF_EXT.test(urlFilename)) {
                      return <PdfPreview href={href} filename={urlFilename} />;
                    }

                    // Default — download link with icon
                    return (
                      <a
                        href={href}
                        download={urlFilename}
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 text-accent hover:text-accent underline decoration-primary-300 underline-offset-2 cursor-pointer bg-transparent border-none p-0 font-inherit text-inherit transition-colors"
                      >
                        <svg className="w-4 h-4 inline-block flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        {children}
                      </a>
                    );
                  }
                  return (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-accent hover:text-accent underline decoration-primary-300 underline-offset-2 transition-colors"
                    >
                      {children}
                    </a>
                  );
                },
              }}
            >
              {content}
            </ReactMarkdown>
          </div>
        )}
      </div>

      {/* User avatar */}
      {isUser && (
        <div className="flex-shrink-0 ml-3 mt-1">
          <div className="w-8 h-8 rounded-full bg-surface-2 flex items-center justify-center">
            <svg className="w-4 h-4 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
            </svg>
          </div>
        </div>
      )}
    </div>
  );
}
