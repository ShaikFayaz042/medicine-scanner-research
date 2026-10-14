
import { useState } from 'react';
import {
  Play,
  Search,
  RefreshCw,
  MoreVertical,
  ArrowDownUp,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useScanner } from './context';
import {
  Badge,
  PageHeading,
  Stats,
  Schedule,
  Pagination,
  Empty,
} from './shared';
import { RunDrawer } from './run-drawer';

export function RunsPage() {
  const { runs, trigger, search, setNotice } = useScanner();

  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('All Status');
  const [source, setSource] = useState('All Sources');
  const [type, setType] = useState('All Triggers');
  const [selected, setSelected] = useState(null);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(5);
  const [descending, setDescending] = useState(true);

  const filtered = runs
    .filter(
      (r) =>
        `${r.id} ${r.source}`
          .toLowerCase()
          .includes((query || search).toLowerCase()) &&
        (status === 'All Status' || r.status === status) &&
        (source === 'All Sources' || r.source === source) &&
        (type === 'All Triggers' || r.trigger === type)
    )
    .sort((a, b) =>
      descending
        ? b.id.localeCompare(a.id)
        : a.id.localeCompare(b.id)
    );

  return (
    <main className="page-content">
      <PageHeading
        eyebrow="HOME / RUNS / HISTORY"
        title="Runs / History"
        description="Monitor scraper executions, processing stages and ingestion outcomes."
      />

      <Stats kind="runs" />

      <Schedule />

      <section className="panel data-panel">
        <div className="filter-bar">
          <label className="filter-search">
            <Search size={15} />

            <input
              aria-label="Search runs"
              placeholder="Search by run ID, source..."
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(1);
              }}
            />
          </label>

          <select
            aria-label="Filter run status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            {[
              'All Status',
              'Completed',
              'In progress',
              'Failed',
              'Queued',
            ].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>

          <select
            aria-label="Filter run source"
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setPage(1);
            }}
          >
            {[
              'All Sources',
              ...new Set(runs.map((r) => r.source)),
            ].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>

          <select
            aria-label="Filter trigger"
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setPage(1);
            }}
          >
            <option>All Triggers</option>
            <option>Scheduled</option>
            <option>Manual</option>
          </select>

          <span className="filter-date">
            09 Oct 2026 · Sample history
          </span>

          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setNotice(
                'Sample history refreshed. No live service is connected.'
              )
            }
          >
            <RefreshCw />
            Refresh
          </Button>
        </div>

        <div className="table-scroll">
          <table className="runs-table">
            <thead>
              <tr>
                <th>#</th>

                <th>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDescending(!descending)}
                  >
                    Run ID
                    <ArrowDownUp size={12} />
                  </Button>
                </th>

                <th>Trigger</th>
                <th>Source</th>
                <th>Started At</th>
                <th>Duration</th>
                <th>Scraper</th>
                <th>Processing</th>
                <th>Ingestion</th>
                <th>Overall Status</th>
                <th>Actions</th>
              </tr>
            </thead>

            <tbody>
              {filtered
                .slice((page - 1) * size, page * size)
                .map((r, i) => (
                  <tr
                    key={r.id}
                    className={
                      selected === r.id ? 'selected-row' : ''
                    }
                    onClick={() => setSelected(r.id)}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        setSelected(r.id);
                      }
                    }}
                  >
                    <td>{(page - 1) * size + i + 1}</td>

                    <td className="table-link">{r.id}</td>

                    <td>
                      <Badge value={r.trigger} />
                    </td>

                    <td>
                      <span className="source-tag">
                        {r.source}
                      </span>
                    </td>

                    <td>
                      {r.started}
                      <small className="cell-sub">(IST)</small>
                    </td>

                    <td>{r.duration}</td>

                    <td>
                      <Badge value={r.scraper} />
                    </td>

                    <td>
                      <Badge value={r.processing} />
                    </td>

                    <td>
                      <Badge value={r.ingestion} />
                    </td>

                    <td>
                      <Badge value={r.status} />
                    </td>

                    <td>
                      <Button
                        size="icon"
                        variant="ghost"
                        aria-label={`View ${r.id}`}
                      >
                        <MoreVertical />
                      </Button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>

          {!filtered.length && <Empty />}
        </div>

        <Pagination
          page={page}
          setPage={setPage}
          total={filtered.length}
          size={size}
          setSize={setSize}
        />
      </section>

      {selected && (
        <RunDrawer
          id={selected}
          onClose={() => setSelected(null)}
        />
      )}
    </main>
  );
}