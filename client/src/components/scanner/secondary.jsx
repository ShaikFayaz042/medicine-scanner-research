import { useState } from 'react';
import { Search, Database, ArrowUpRight, Settings2, ExternalLink, LoaderCircle, ShieldCheck, LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PageHeading, SectionTitle, Empty, Schedule } from './shared';
import { useScanner } from './context';
import { loginMedicineUser, verifyManualEntry } from '@/services/medicineApi';

const emptyMedicineFields = {
	name: '',
	salt: '',
	batchNumber: '',
	mfdDate: '',
	expDate: '',
	dose: '',
};

const indicatorStyles = {
	RED: { label: 'RED', title: 'Regulatory restriction recorded', kind: 'danger' },
	YELLOW: { label: 'YELLOW', title: 'Caution / quality alert', kind: 'warning' },
	GREEN: { label: 'GREEN', title: 'No indexed alert found', kind: 'success' },
	UNKNOWN: { label: 'UNKNOWN', title: 'Review regulatory records', kind: 'neutral' },
};

export function LookupPage() {
	const [session, setSession] = useState(() => {
		try {
			return JSON.parse(sessionStorage.getItem('medicine-scanner-session'));
		} catch {
			return null;
		}
	});
	const [credentials, setCredentials] = useState({ email: '', password: '' });
	const [fields, setFields] = useState(emptyMedicineFields);
	const [result, setResult] = useState(null);
	const [signingIn, setSigningIn] = useState(false);
	const [verifying, setVerifying] = useState(false);
	const [error, setError] = useState('');

	async function handleSignIn(event) {
		event.preventDefault();
		setSigningIn(true);
		setError('');
		try {
			const signedIn = await loginMedicineUser(credentials.email.trim(), credentials.password);
			sessionStorage.setItem('medicine-scanner-session', JSON.stringify(signedIn));
			setSession(signedIn);
			setCredentials(current => ({ ...current, password: '' }));
		} catch (loginError) {
			setError(loginError.message || 'Sign-in failed. Please try again.');
		} finally {
			setSigningIn(false);
		}
	}

	async function handleVerify(event) {
		event.preventDefault();
		if (!fields.batchNumber.trim()) {
			setError('A batch number is needed to check the register.');
			return;
		}

		setVerifying(true);
		setError('');
		setResult(null);
		try {
			setResult(await verifyManualEntry(fields, session.token));
		} catch (verifyError) {
			if (verifyError.status === 401) {
				sessionStorage.removeItem('medicine-scanner-session');
				setSession(null);
			}
			setError(verifyError.message || 'Could not verify this medicine. Please try again.');
		} finally {
			setVerifying(false);
		}
	}

	function signOut() {
		sessionStorage.removeItem('medicine-scanner-session');
		setSession(null);
		setResult(null);
		setError('');
	}

	function updateField(key, value) {
		setFields(current => ({ ...current, [key]: value }));
		setError('');
	}

	return <main className="page-content">
		<PageHeading eyebrow="MEDICHECK" title="Medicine Lookup" description="Check a medicine batch against indexed regulatory and quality records."/>
		<section className="panel lookup-panel">
			<SectionTitle icon={Search} title={session ? 'Enter medicine details' : 'Sign in to verify'}/>
			{!session ? <form className="medicine-auth-form" onSubmit={handleSignIn}>
				<p>Use the same MediCheck account as the mobile app.</p>
				<label>Email<input type="email" autoComplete="username" required value={credentials.email} onChange={event => setCredentials(current => ({ ...current, email: event.target.value }))}/></label>
				<label>Password<input type="password" autoComplete="current-password" required value={credentials.password} onChange={event => setCredentials(current => ({ ...current, password: event.target.value }))}/></label>
				<Button type="submit" disabled={signingIn}>{signingIn ? <LoaderCircle className="medicine-search-spinner"/> : <ShieldCheck/>}{signingIn ? 'Signing in' : 'Sign in'}</Button>
			</form> : <>
				<div className="medicine-session-bar"><span>Signed in as {session.user?.email || session.user?.name}</span><Button type="button" size="sm" variant="ghost" onClick={signOut}><LogOut/>Sign out</Button></div>
				<form className="manual-entry-form" onSubmit={handleVerify}>
					<label>Medicine name<input placeholder="e.g. Tylenol" autoComplete="off" value={fields.name} onChange={event => updateField('name', event.target.value)}/></label>
					<label>Active ingredient<input placeholder="e.g. Paracetamol" autoComplete="off" value={fields.salt} onChange={event => updateField('salt', event.target.value)}/></label>
					<label>Batch number <span className="required-mark">Required</span><input placeholder="e.g. B.NO.12345" autoComplete="off" required value={fields.batchNumber} onChange={event => updateField('batchNumber', event.target.value)}/><small>Usually printed near the expiry date as B.NO. or LOT.</small></label>
					<div className="manual-entry-date-row">
						<label>Manufactured<input placeholder="MM/YYYY" value={fields.mfdDate} onChange={event => updateField('mfdDate', event.target.value)}/></label>
						<label>Expires<input placeholder="MM/YYYY" value={fields.expDate} onChange={event => updateField('expDate', event.target.value)}/></label>
					</div>
					<label>Dose<input placeholder="e.g. 500mg" autoComplete="off" value={fields.dose} onChange={event => updateField('dose', event.target.value)}/></label>
					<div className="manual-entry-actions">
						<Button type="submit" disabled={verifying}>{verifying ? <LoaderCircle className="medicine-search-spinner"/> : <ShieldCheck/>}{verifying ? 'Checking register' : 'Verify medicine'}</Button>
						<Button type="button" variant="ghost" disabled={verifying} onClick={() => { setFields(emptyMedicineFields); setResult(null); setError(''); }}>Clear form</Button>
					</div>
				</form>
			</>}
			{error && <p className="medicine-search-error" role="alert">{error}</p>}
			{verifying && <p className="medicine-search-message" role="status">Checking indexed regulatory records…</p>}
			{result && <ManualResult result={result}/>}
		</section>
	</main>;
}

function ManualResult({ result }) {
	const matches = Array.isArray(result.matches) ? result.matches : [];
	const firstMatch = matches[0];
	const product = firstMatch?.product ?? {};
	const assessment = firstMatch?.assessment ?? {};
	const rawIndicator = String(assessment.indicator || '').toUpperCase();
	const indicator = indicatorStyles[rawIndicator] ? rawIndicator : result.status === 'unsafe' ? 'RED' : 'UNKNOWN';
	const style = indicatorStyles[indicator];
	const fields = result.fields ?? {};
	const name = fields.name || product.name || 'Medicine scan results';
	const dose = fields.dose || product.strength || '';
	const heading = dose && !name.toLowerCase().includes(dose.toLowerCase()) ? `${name} ${dose}` : name;
	const ingredients = Array.isArray(product.ingredients) ? product.ingredients.map(item => item?.name).filter(Boolean).join(', ') : '';
	const details = [
		['Brand / Name', product.brand_name || product.name || fields.name],
		['Generic ingredient', product.generic_name || ingredients || fields.salt],
		['Strength', dose],
		['Dosage form', product.dosage_form],
		['Manufacturer', product.manufacturer],
	].filter(([, value]) => value);
	const packDetails = [
		['Batch', fields.batchNumber],
		['Manufactured', fields.mfdDate],
		['Expires', fields.expDate],
		['GTIN', result.gtin],
		['Serial', result.serial],
	].filter(([, value]) => value);
	const events = matches.flatMap(match => (Array.isArray(match.regulatory_events) ? match.regulatory_events : []).map(event => ({ event, productName: match.product?.name })));
	const summary = assessment.summary || result.message || 'No regulatory assessment was returned for this verification.';
	const disclaimer = assessment.disclaimer || 'Based on regulatory records currently available in the system. This is not medical advice. Consult your doctor.';

	return <section className="manual-result" aria-live="polite">
		<h2>Medicine Info</h2>
		<div className="manual-result-card">
			<h3>{heading}</h3>
			{details.length ? details.map(([label, value]) => <p key={label}><strong>{label}:</strong> {value}</p>) : <p>No medicine details were captured.</p>}
			{packDetails.length > 0 && <div className="manual-pack-details"><h4>Pack details</h4>{packDetails.map(([label, value]) => <p key={label}><strong>{label}:</strong> {value}</p>)}</div>}
		</div>

		<h2>Regulatory overview</h2>
		<div className={`manual-overview manual-overview-${style.kind}`}>
			<div><strong>{style.label} · {style.title}</strong><p>{summary}</p></div>
			<p className="manual-overview-note">{events.length
				? `${events.length} related regulatory ${events.length === 1 ? 'record' : 'records'} found in the indexed data.`
				: matches.length
					? 'No related regulatory events were returned for this matched product. This is not a guarantee of safety.'
					: 'No matching product was found in the indexed records. This does not establish whether the pack is authentic or safe.'}</p>
		</div>

		<h2>Related regulatory records{events.length > 0 && <span className="record-count">{events.length}</span>}</h2>
		{events.length ? <div className="manual-record-list">{events.map(({ event, productName }, index) => {
			const source = event.source ?? {};
			const extraDetails = [['Legal status', event.legal_status], ['Official record', source.title], ['Published', source.publication_date]].filter(([, value]) => value);
			return <article className="manual-result-card manual-record" key={event.event_id || `${event.source_record_id || 'event'}-${index}`}>
				{productName && <strong className="manual-event-product">{productName}</strong>}
				<h3>{String(event.event_type || 'Regulatory record').replaceAll('_', ' ')}</h3>
				{event.batch_number && <p><strong>Affected batch:</strong> {event.batch_number}</p>}
				{event.reason && <p><strong>Issue:</strong> {event.reason}</p>}
				{event.scope && <p><strong>Event scope:</strong> {String(event.scope).toLowerCase()}</p>}
				{event.status && <p><strong>Status:</strong> {String(event.status).replaceAll('_', ' ')}</p>}
				<div className="manual-record-actions">
					{extraDetails.length > 0 && <details><summary>More info</summary>{extraDetails.map(([label, value]) => <p key={label}><strong>{label}:</strong> {value}</p>)}</details>}
					{source.source_url ? <a href={source.source_url} target="_blank" rel="noreferrer">View official source <ExternalLink size={14}/></a> : <span>Source link unavailable</span>}
				</div>
			</article>;
		})}</div> : <Empty message={matches.length ? 'No related regulatory records are available for this result.' : 'Regulatory records are unavailable because no product match was found.'}/>}
		<p className="manual-result-disclaimer">{disclaimer}</p>
	</section>;
}
export function SourcesPage() { const { documents } = useScanner(); return <main className="page-content"><PageHeading eyebrow="MEDICHECK" title="Regulatory Sources" description="Government sources monitored by the collection pipeline."/><section className="panel data-panel"><SectionTitle icon={Database} title="Source registry"><span className="mini-label">Sample configuration</span></SectionTitle><div className="table-scroll"><table><thead><tr><th>Source</th><th>Publisher</th><th>Sample Documents</th><th>Connection</th><th>Website</th></tr></thead><tbody>{['CDSCO FDC', 'CDSCO Alerts', 'Banned Drugs', 'IPC / PvPI', 'NSQ / Spurious'].map(s => <tr key={s}><td><span className="section-icon"><Database size={16}/></span> <strong>{s}</strong></td><td>{s === 'IPC / PvPI' ? 'Indian Pharmacopoeia Commission' : 'Central Drugs Standard Control Organisation'}</td><td>{documents.filter(d => d.source === s).length}</td><td><span className="badge badge-neutral">Not connected</span></td><td><Button variant="link" size="sm" asChild><a href={s === 'IPC / PvPI' ? 'https://ipc.gov.in/' : 'https://cdsco.gov.in/'} target="_blank" rel="noreferrer">Visit <ArrowUpRight /></a></Button></td></tr>)}</tbody></table></div></section></main>; }
export function SettingsPage() { return <main className="page-content"><PageHeading eyebrow="WORKSPACE" title="Settings" description="Manage workspace identity and automation preferences."/><div className="settings-grid"><section className="panel"><SectionTitle icon={Settings2} title="Workspace"/><div className="settings-list"><div><small>Workspace name</small><strong>MediCheck</strong></div><div><small>Administrator</small><strong>Shaik Fayaz</strong></div><div><small>Environment</small><strong>Demo · No external services connected</strong></div><div><small>Approval policy</small><strong>Versioned normalized batch review</strong></div></div></section><Schedule /></div></main>; }
