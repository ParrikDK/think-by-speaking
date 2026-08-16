// All supported languages, sorted alphabetically by English name
const LANGUAGES = [
  { code: 'ar', native: 'العربية', english: 'Arabic' },
  { code: 'az', native: 'Azərbaycan dili', english: 'Azerbaijani' },
  { code: 'bn', native: 'বাংলা', english: 'Bengali' },
  { code: 'yue', native: '粵語', english: 'Cantonese' },
  { code: 'cs', native: 'Čeština', english: 'Czech' },
  { code: 'nl', native: 'Nederlands', english: 'Dutch' },
  { code: 'en', native: 'English', english: 'English' },
  { code: 'fil', native: 'Filipino', english: 'Filipino' },
  { code: 'fr', native: 'Français', english: 'French' },
  { code: 'de', native: 'Deutsch', english: 'German' },
  { code: 'el', native: 'Ελληνικά', english: 'Greek' },
  { code: 'he', native: 'עברית', english: 'Hebrew' },
  { code: 'hi', native: 'हिन्दी', english: 'Hindi' },
  { code: 'id', native: 'Bahasa Indonesia', english: 'Indonesian' },
  { code: 'it', native: 'Italiano', english: 'Italian' },
  { code: 'ja', native: '日本語', english: 'Japanese' },
  { code: 'ko', native: '한국어', english: 'Korean' },
  { code: 'ms', native: 'Bahasa Melayu', english: 'Malay' },
  { code: 'zh', native: '中文', english: 'Mandarin Chinese' },
  { code: 'pl', native: 'Polski', english: 'Polish' },
  { code: 'pt', native: 'Português', english: 'Portuguese' },
  { code: 'ru', native: 'Русский', english: 'Russian' },
  { code: 'es', native: 'Español', english: 'Spanish' },
  { code: 'sw', native: 'Kiswahili', english: 'Swahili' },
  { code: 'sv', native: 'Svenska', english: 'Swedish' },
  { code: 'ta', native: 'தமிழ்', english: 'Tamil' },
  { code: 'th', native: 'ไทย', english: 'Thai' },
  { code: 'zh-TW', native: '繁體中文', english: 'Traditional Chinese' },
  { code: 'tr', native: 'Türkçe', english: 'Turkish' },
  { code: 'ur', native: 'اردو', english: 'Urdu' },
  { code: 'vi', native: 'Tiếng Việt', english: 'Vietnamese' },
];

const FLAGS = {
  ar: '🇸🇦', az: '🇦🇿', bn: '🇧🇩', yue: '🇭🇰', cs: '🇨🇿', nl: '🇳🇱',
  en: '🇬🇧', fil: '🇵🇭', fr: '🇫🇷', de: '🇩🇪', el: '🇬🇷', he: '🇮🇱',
  hi: '🇮🇳', id: '🇮🇩', it: '🇮🇹', ja: '🇯🇵', ko: '🇰🇷', ms: '🇲🇾',
  zh: '🇨🇳', 'zh-TW': '🇹🇼', pl: '🇵🇱', pt: '🇵🇹', ru: '🇷🇺', es: '🇪🇸',
  sw: '🇰🇪', sv: '🇸🇪', ta: '🇮🇳', th: '🇹🇭', tr: '🇹🇷', ur: '🇵🇰',
  vi: '🇻🇳',
};

export function flagFor(code) {
  return FLAGS[code] || '';
}

export default LANGUAGES;
