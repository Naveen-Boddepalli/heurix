// Pure zero-dependency browser ZIP generator and config exporter
// Implements standard PKZIP Store (uncompressed) format compatible with all operating systems

const CRC_TABLE = new Uint32Array(256);
for (let i = 0; i < 256; i++) {
  let c = i;
  for (let k = 0; k < 8; k++) {
    c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
  }
  CRC_TABLE[i] = c >>> 0;
}

function calculateCRC32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    crc = CRC_TABLE[(crc ^ data[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

export interface ExportableFile {
  path: string;
  content: string;
}

export function buildZipBlob(files: ExportableFile[]): Blob {
  const encoder = new TextEncoder();
  const fileEntries: Array<{
    nameBytes: Uint8Array;
    dataLength: number;
    crc: number;
    offset: number;
  }> = [];

  let offset = 0;
  const parts: Uint8Array[] = [];

  for (const file of files) {
    const cleanPath = file.path.replace(/^\/+/, '');
    const nameBytes = encoder.encode(cleanPath);
    const dataBytes = encoder.encode(file.content);
    const crc = calculateCRC32(dataBytes);

    const localHeader = new Uint8Array(30 + nameBytes.length);
    const view = new DataView(localHeader.buffer);

    view.setUint32(0, 0x04034b50, true); // Local header signature
    view.setUint16(4, 20, true);         // Version needed (2.0)
    view.setUint16(6, 0x0800, true);     // Flags (UTF-8)
    view.setUint16(8, 0, true);          // Compression (Store)
    view.setUint16(10, 0, true);         // Mod time
    view.setUint16(12, 0, true);         // Mod date
    view.setUint32(14, crc, true);       // CRC-32
    view.setUint32(18, dataBytes.length, true); // Compressed size
    view.setUint32(22, dataBytes.length, true); // Uncompressed size
    view.setUint16(26, nameBytes.length, true); // File name length
    view.setUint16(28, 0, true);         // Extra field length
    localHeader.set(nameBytes, 30);

    parts.push(localHeader);
    parts.push(dataBytes);

    fileEntries.push({
      nameBytes,
      dataLength: dataBytes.length,
      crc,
      offset,
    });

    offset += localHeader.length + dataBytes.length;
  }

  const cdOffset = offset;
  let cdSize = 0;

  for (const entry of fileEntries) {
    const cdHeader = new Uint8Array(46 + entry.nameBytes.length);
    const view = new DataView(cdHeader.buffer);

    view.setUint32(0, 0x02014b50, true); // Central directory signature
    view.setUint16(4, 20, true);         // Version made by
    view.setUint16(6, 20, true);         // Version needed
    view.setUint16(8, 0x0800, true);     // Flags (UTF-8)
    view.setUint16(10, 0, true);         // Compression (Store)
    view.setUint16(12, 0, true);         // Mod time
    view.setUint16(14, 0, true);         // Mod date
    view.setUint32(16, entry.crc, true); // CRC-32
    view.setUint32(20, entry.dataLength, true); // Compressed size
    view.setUint32(24, entry.dataLength, true); // Uncompressed size
    view.setUint16(28, entry.nameBytes.length, true); // Name length
    view.setUint16(30, 0, true);         // Extra field length
    view.setUint16(32, 0, true);         // Comment length
    view.setUint16(34, 0, true);         // Disk number start
    view.setUint16(36, 0, true);         // Internal attributes
    view.setUint32(38, (0o100644 << 16) >>> 0, true); // External attributes (rw-r--r--)
    view.setUint32(42, entry.offset, true); // Relative offset of local header
    cdHeader.set(entry.nameBytes, 46);

    parts.push(cdHeader);
    cdSize += cdHeader.length;
  }

  const eocd = new Uint8Array(22);
  const eocdView = new DataView(eocd.buffer);
  eocdView.setUint32(0, 0x06054b50, true); // EOCD signature
  eocdView.setUint16(4, 0, true);          // Disk number
  eocdView.setUint16(6, 0, true);          // Start disk
  eocdView.setUint16(8, fileEntries.length, true);  // Entries on this disk
  eocdView.setUint16(10, fileEntries.length, true); // Total entries
  eocdView.setUint32(12, cdSize, true);             // CD size
  eocdView.setUint32(16, cdOffset, true);           // CD offset
  eocdView.setUint16(20, 0, true);                  // Comment length

  parts.push(eocd);

  return new Blob(parts as BlobPart[], { type: 'application/zip' });
}

export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function downloadZipArchive(filename: string, files: ExportableFile[]): void {
  const blob = buildZipBlob(files);
  triggerBlobDownload(blob, filename.endsWith('.zip') ? filename : `${filename}.zip`);
}

export function formatAllConfigsText(files: ExportableFile[]): string {
  return files
    .map(
      (f) =>
        `# ==============================================================================\n# Target: ${f.path}\n# ==============================================================================\n${f.content.trimEnd()}\n`
    )
    .join('\n');
}

export function generateSetupShellScript(files: ExportableFile[]): string {
  const lines: string[] = [
    '#!/usr/bin/env bash',
    '# Synthesized by Heurix (hx) Deterministic Config Engine',
    'set -euo pipefail',
    '',
    `echo "Applying ${files.length} synthesized configuration files..."`,
    '',
  ];

  for (const file of files) {
    const dir = file.path.includes('/') ? file.path.substring(0, file.path.lastIndexOf('/')) : '';
    if (dir) {
      lines.push(`mkdir -p "${dir}"`);
    }
    lines.push(`cat << 'EOF' > "${file.path}"`);
    lines.push(file.content.trimEnd());
    lines.push('EOF');
    lines.push(`echo "✔ Created ${file.path}"`);
    lines.push('');
  }

  lines.push('echo "All Heurix configurations successfully applied!"');
  return lines.join('\n');
}
