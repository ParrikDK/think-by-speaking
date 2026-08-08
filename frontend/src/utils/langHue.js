// Deterministic per-language accent hue (0-359) from the language code.
// Gives each language cell a stable identity color without flags.
export default function langHue(code) {
  let h = 0;
  for (const ch of String(code)) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}
