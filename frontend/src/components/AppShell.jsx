import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom';
import { LayoutGrid, LogOut, X } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import OfflineBanner from './OfflineBanner';
import LanguageSwitcher from './LanguageSwitcher';

/**
 * Coquille commune a tous les roles (maquette « Meetings ») :
 * - ordinateur (>= 1024px) : sidebar blanche ;
 * - mobile : barre en pilule en bas + bouton d'action orange + panneau « Menu ».
 *
 * links : [{ to, label, icon, count?, section? }]  (section = titre de groupe)
 * dock  : jusqu'a 3 liens de la pilule (le 4e bouton est toujours « Menu »)
 * fab   : { label, icon, to } ou { label, icon, onClick } — optionnel
 * flushPaths : chemins dont la page gere son propre en-tete pleine largeur
 */
export default function AppShell({ roleLabel, links, dock = [], fab, flushPaths = [], children }) {
  const { logout, user } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  const isActive = (path) => location.pathname === path;
  const flush = flushPaths.includes(location.pathname);
  const pending = links.some((l) => l.count > 0);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const renderLinks = (onClick) => links.map(({ to, label, icon: Icon, count, section }, i) => (
    <div key={to}>
      {section && (
        <p style={{ margin: `${i === 0 ? 0 : 0.9}rem 0.75rem 0.35rem`, fontSize: '0.75rem', color: 'var(--color-stone)' }}>{section}</p>
      )}
      <Link to={to} onClick={onClick} className={`mt-side__link${isActive(to) ? ' is-active' : ''}`}>
        <Icon size={19} />
        {label}
        {count > 0 && <span className="mt-side__count">{count}</span>}
      </Link>
    </div>
  ));

  const footer = (
    <div className="mt-side__foot">
      <LanguageSwitcher variant="block" />
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0 0.25rem' }}>
        <div style={{ width: 36, height: 36, borderRadius: '50%', background: '#FFF1E6', color: 'var(--color-ore-dark)', display: 'grid', placeItems: 'center', fontWeight: 600, flexShrink: 0 }}>
          {(user?.name || roleLabel || 'M').slice(0, 1).toUpperCase()}
        </div>
        <div style={{ minWidth: 0 }}>
          <p style={{ margin: 0, fontSize: '0.88rem', fontWeight: 600, color: 'var(--color-white)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user?.name}</p>
          <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--color-stone)' }}>{roleLabel}</p>
        </div>
      </div>
      <button type="button" onClick={handleLogout} className="mt-side__link" style={{ border: 0, background: 'transparent', cursor: 'pointer', color: 'var(--color-ruby)', fontFamily: 'inherit' }}>
        <LogOut size={19} />
        {t('user.logout')}
      </button>
    </div>
  );

  const FabIcon = fab?.icon;

  return (
    <div className="mt-shell">
      <aside className="mt-side">
        <div className="mt-side__brand">
          <img src="/logo-mark.png" alt="" className="mt-side__mark" width="44" height="44" />
          <div>
            <strong>MineTrack</strong>
            <span>{roleLabel}</span>
          </div>
        </div>
        {renderLinks()}
        {footer}
      </aside>

      <main className={`mt-main${flush ? ' mt-main--flush' : ''}`}>
        <OfflineBanner />
        {children ?? <Outlet />}
      </main>

      <nav className="mt-dock" aria-label={t('app.main_nav')}>
        <div className="mt-dock__pill">
          {dock.map(({ to, label, icon: Icon }) => (
            <Link key={to} to={to} aria-label={label} title={label} className={`mt-dock__item${isActive(to) ? ' is-active' : ''}`}>
              <Icon size={23} strokeWidth={1.8} />
            </Link>
          ))}
          <button type="button" aria-label={t('app.menu')} title={t('app.menu')} className="mt-dock__item" onClick={() => setMenuOpen(true)}>
            <LayoutGrid size={23} strokeWidth={1.8} />
            {pending && <span className="mt-round__dot" />}
          </button>
        </div>
        {fab && (fab.to ? (
          <Link to={fab.to} aria-label={fab.label} title={fab.label} className="mt-fab"><FabIcon size={26} /></Link>
        ) : (
          <button type="button" onClick={fab.onClick} aria-label={fab.label} title={fab.label} className="mt-fab"><FabIcon size={26} /></button>
        ))}
      </nav>

      {menuOpen && (
        <>
          <div className="mt-sheet-backdrop" onClick={() => setMenuOpen(false)} />
          <div className="mt-sheet" role="dialog" aria-label={t('app.menu')}>
            <div className="mt-sheet__grip" />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <h3 style={{ margin: 0, fontWeight: 500 }}>{t('app.menu')}</h3>
              <button type="button" className="mt-round" style={{ width: 38, height: 38 }} aria-label={t('app.close')} onClick={() => setMenuOpen(false)}>
                <X size={18} />
              </button>
            </div>
            {renderLinks(() => setMenuOpen(false))}
            {footer}
          </div>
        </>
      )}
    </div>
  );
}
