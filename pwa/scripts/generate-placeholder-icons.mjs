// Genera los íconos placeholder de public/icons/*.png sin depender de ninguna librería de
// imágenes (no hay PIL/ImageMagick disponible en este entorno) — encoder PNG mínimo a mano
// usando solo `zlib` (built-in de Node). Dibuja el mismo mark que public/icons/icon.svg
// (fondo #0d0d14 + círculo índigo #6366f1 centrado) en los tamaños que pide manifest.json /
// apple-touch-icon. Placeholder documentado — reemplazar por el logo real cuando exista,
// re-corriendo este script o subiendo PNGs definitivos con el mismo nombre de archivo.
//
// Uso: node scripts/generate-placeholder-icons.mjs
import { deflateSync } from "node:zlib";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.resolve(__dirname, "../public/icons");

const BG = [0x0d, 0x0d, 0x14]; // --color-bg
const ACCENT = [0x63, 0x66, 0xf1]; // --color-accent

function crc32(buf) {
  let c;
  const table = crc32.table ?? (crc32.table = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })());
  let crc = 0xffffffff;
  for (let i = 0; i < buf.length; i++) crc = table[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const typeBuf = Buffer.from(type, "ascii");
  const lenBuf = Buffer.alloc(4);
  lenBuf.writeUInt32BE(data.length, 0);
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([lenBuf, typeBuf, data, crcBuf]);
}

function buildPng(size, maskableSafe) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr.writeUInt8(8, 8); // bit depth
  ihdr.writeUInt8(2, 9); // color type: RGB
  ihdr.writeUInt8(0, 10);
  ihdr.writeUInt8(0, 11);
  ihdr.writeUInt8(0, 12);

  // Radio del círculo: si es maskable, se reduce para respetar la zona segura (círculo
  // inscripto al ~80% del lienzo, como pide la spec de íconos maskable).
  const cx = size / 2;
  const cy = size / 2;
  const r = size * (maskableSafe ? 0.32 : 0.36);

  const rowSize = size * 3;
  const raw = Buffer.alloc((rowSize + 1) * size);
  for (let y = 0; y < size; y++) {
    const rowStart = y * (rowSize + 1);
    raw[rowStart] = 0; // filter: none
    for (let x = 0; x < size; x++) {
      const dx = x - cx;
      const dy = y - cy;
      const inCircle = dx * dx + dy * dy <= r * r;
      const [rr, gg, bb] = inCircle ? ACCENT : BG;
      const px = rowStart + 1 + x * 3;
      raw[px] = rr;
      raw[px + 1] = gg;
      raw[px + 2] = bb;
    }
  }

  const idat = deflateSync(raw);
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  return Buffer.concat([
    signature,
    chunk("IHDR", ihdr),
    chunk("IDAT", idat),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const targets = [
  { file: "icon-192.png", size: 192, maskableSafe: false },
  { file: "icon-512.png", size: 512, maskableSafe: false },
  { file: "icon-maskable-512.png", size: 512, maskableSafe: true },
  { file: "icon-180.png", size: 180, maskableSafe: false }, // apple-touch-icon
];

for (const t of targets) {
  writeFileSync(path.join(outDir, t.file), buildPng(t.size, t.maskableSafe));
  console.log(`generado ${t.file}`);
}
