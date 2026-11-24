import { useTranslation } from 'react-i18next';
import { Globe, ChevronDown } from 'lucide-react';
import { ensureLocaleLoaded } from '../i18n';

// Meme liste et meme ordre partout (connexion, barre laterale, menu mobile).
const LANGUAGES = [
  { code: 'fr', label: 'Français' },
  { code: 'en', label: 'English' },
  { code: 'sw', label: 'Kiswahili' },
  { code: 'ln', label: 'Lingala' },
  { code: 'kg', label: 'Kikongo' },
  { code: 'lu', label: 'Tshiluba' },
];

/**
 * Bulle de changement de langue.
 * Toute la bulle est cliquable : un <select> natif transparent la recouvre,
 * ce qui ouvre la liste systeme (pratique au doigt sur telephone) et reste
 * accessible au clavier et aux lecteurs d'ecran.
 *
 * variant="block" : pleine largeur (barre laterale, menu mobile).
 */
export default function LanguageSwitcher({ variant, className = '', style }) {
  const { t, i18n } = useTranslation();
  const code = (i18n.language || i18n.resolvedLanguage || 'fr').slice(0, 2);
  const current = LANGUAGES.find((l) => l.code === code) || LANGUAGES[0];

  const changeLanguage = async (next) => {
    await ensureLocaleLoaded(next);
    i18n.changeLanguage(next);
    try { localStorage.setItem('i18nextLng', next); } catch { /* stockage indisponible */ }
  };

  return (
    <label className={`lang-bubble${variant === 'block' ? ' lang-bubble--block' : ''} ${className}`.trim()} style={style}>
      <Globe size={17} strokeWidth={1.8} aria-hidden="true" />
      <span className="lang-bubble__label">{current.label}</span>
      <ChevronDown size={16} strokeWidth={2} aria-hidden="true" className="lang-bubble__chev" />
      <select
        aria-label={t('login.choose_language')}
        value={current.code}
        onChange={(e) => changeLanguage(e.target.value)}
      >
        {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
      </select>
    </label>
  );
}
