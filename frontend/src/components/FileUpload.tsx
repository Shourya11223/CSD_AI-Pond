import { useCallback, useRef, useState } from 'react';
import { fmtFileSize, validateFile } from '../lib/utils';

interface Props {
  file: File | null;
  onFileSelected: (file: File | null) => void;
  disabled?: boolean;
}

const SAMPLE_FILENAME = 'contours_1m.kml';
const SAMPLE_URL = '/sample/contours_1m.kml';

/**
 * Drag-and-drop upload zone with file validation and a sample-file loader.
 */
export function FileUpload({ file, onFileSelected, disabled }: Props) {
  const [isDragging, setIsDragging] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const acceptFile = useCallback(
    (candidate: File) => {
      const err = validateFile(candidate);
      if (err) {
        setValidationError(err);
        onFileSelected(null);
        return;
      }
      setValidationError(null);
      onFileSelected(candidate);
    },
    [onFileSelected],
  );

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) setIsDragging(true);
  };
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (disabled) return;
    const f = e.dataTransfer.files?.[0];
    if (f) acceptFile(f);
  };
  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) acceptFile(f);
    e.target.value = '';
  };

  const loadSample = async () => {
    if (disabled) return;
    try {
      const resp = await fetch(SAMPLE_URL);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const sample = new File([blob], SAMPLE_FILENAME, {
        type: 'application/vnd.google-earth.kml+xml',
      });
      acceptFile(sample);
    } catch {
      setValidationError(
        `Could not load the sample file. Place ${SAMPLE_FILENAME} in public/sample/ to enable.`,
      );
    }
  };

  const removeFile = () => {
    onFileSelected(null);
    setValidationError(null);
  };

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-[0.1em] text-terrain-700">
          Contour Source
        </h2>
        {file && !disabled && (
          <button
            onClick={removeFile}
            className="text-[11px] text-terrain-500 hover:text-water-600 transition-colors"
          >
            Remove
          </button>
        )}
      </div>

      {!file ? (
        <DropZone
          isDragging={isDragging}
          disabled={disabled}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          inputRef={inputRef}
          onChange={handleInput}
        />
      ) : (
        <FilePreview file={file} onRemove={removeFile} disabled={disabled} />
      )}

      {validationError && (
        <p className="text-[12px] text-red-600 leading-snug">{validationError}</p>
      )}

      {!file && (
        <button
          onClick={loadSample}
          disabled={disabled}
          className="w-full text-[12px] text-water-700 hover:text-water-800 hover:bg-water-50 py-1.5 rounded-lg transition-colors disabled:opacity-50"
        >
          ↻ Load sample contours_1m.kml
        </button>
      )}
    </div>
  );
}
// ============================================================
// Subcomponents
// ============================================================

interface DropZoneProps {
  isDragging: boolean;
  disabled?: boolean;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onClick: () => void;
  inputRef: React.RefObject<HTMLInputElement>;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

function DropZone({
  isDragging,
  disabled,
  onDragOver,
  onDragLeave,
  onDrop,
  onClick,
  inputRef,
  onChange,
}: DropZoneProps) {
  return (
    <div
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onClick={() => !disabled && onClick()}
      className={[
        'relative border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all',
        isDragging
          ? 'border-water-500 bg-water-50 scale-[1.02]'
          : 'border-terrain-200 hover:border-water-400 hover:bg-water-50/30',
        disabled ? 'opacity-50 pointer-events-none' : '',
      ].join(' ')}
      role="button"
      tabIndex={0}
    >
      <input ref={inputRef} type="file" accept=".kml,.kmz" onChange={onChange} className="hidden" />
      <div className="flex flex-col items-center gap-2">
        <svg className="w-8 h-8 text-terrain-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
        </svg>
        <div className="text-sm font-medium text-terrain-700">
          {isDragging ? 'Drop the file here' : 'Drop your KML or KMZ here'}
        </div>
        <div className="text-[11px] text-terrain-400">or click to browse · max 10 MB</div>
      </div>
    </div>
  );
}

interface FilePreviewProps {
  file: File;
  onRemove: () => void;
  disabled?: boolean;
}

function FilePreview({ file, onRemove, disabled }: FilePreviewProps) {
  return (
    <div className="border border-terrain-100 rounded-xl p-3 flex items-center gap-3 bg-terrain-50/50">
      <div className="w-9 h-9 rounded-lg bg-water-100 flex items-center justify-center shrink-0">
        <svg className="w-5 h-5 text-water-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-terrain-900 truncate">{file.name}</p>
        <p className="text-[11px] text-terrain-500 font-mono">{fmtFileSize(file.size)}</p>
      </div>
      {!disabled && (
        <button
          onClick={onRemove}
          className="shrink-0 p-1.5 text-terrain-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors"
          aria-label="Remove file"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  );
}