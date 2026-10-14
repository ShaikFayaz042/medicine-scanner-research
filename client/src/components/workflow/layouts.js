// Static layout. Lanes go left→right:
// [Trigger] → [Sources] → [Orchestration] → [Processing] → [Commit]

const PANEL_PAD_X = 24
const PANEL_PAD_TOP = 44
const PANEL_PAD_BOTTOM = 24

export const SYSTEM_PANELS = [
  { id: 'panel-trigger',  label: 'Trigger',        x: -10,  y: 220,  width: 250, height: 200 },
  { id: 'panel-sources',  label: 'Sources',        x: 100,  y: -160, width: 850, height: 340 },
  { id: 'panel-scraper',  label: 'Scraper',        x: 300,  y: 500, width: 500, height: 260 },
  { id: 'panel-orch',     label: 'Orchestration',  x: 1000, y: 220, width: 250, height: 300 },
  { id: 'panel-process',  label: 'Processing',     x: 1300, y: 140, width: 300, height: 450 },
  { id: 'panel-commit',   label: 'Commit & Storage', x: 1700, y: 120, width: 400, height: 500 },
]

export const SYSTEM_NODES = [
  // Trigger lane
  { id: 'scheduler',  type: 'service', tone: 'amber', position: { x: 20,  y: 300 }, data: { label: 'Scheduler',     sub: 'Cron trigger',     icon: 'clock' } },
  { id: 'scraper',    type: 'service', tone: 'amber', position: { x: 460, y: 530 }, data: { label: 'Scraper',       sub: 'ECS Fargate',      icon: 'globe' } },

  // Sources lane
  { id: 'data-source-1', type: 'source', tone: 'slate', position: { x: 124, y: -100 }, style: { width: 150 }, data: { label: 'CDSCO Alerts', sub: 'PDF safety alerts', icon: 'code', compact: true } },
  { id: 'data-source-2', type: 'source', tone: 'slate', position: { x: 284, y: -100 }, style: { width: 150 }, data: { label: 'CDSCO FDC', sub: 'Fixed-dose combinations', icon: 'db', compact: true } },
  { id: 'data-source-3', type: 'source', tone: 'slate', position: { x: 444, y: -100 }, style: { width: 150 }, data: { label: 'Banned Drugs', sub: 'CDSCO drug list', icon: 'db', compact: true } },
  { id: 'data-source-4', type: 'source', tone: 'slate', position: { x: 604, y: -100 }, style: { width: 150 }, data: { label: 'IPC PvPI', sub: 'Drug Safety Alerts', icon: 'globe', compact: true } },
  { id: 'data-source-5', type: 'source', tone: 'slate', position: { x: 764, y: -100 }, style: { width: 150 }, data: { label: 'CDSCO NSQ', sub: 'NSQ + Spurious JSON API', icon: 'db', compact: true } },
  { id: 'source-queue', type: 'service', tone: 'sky', position: { x: 435, y: 70 }, data: { label: 'Data Source Queue', sub: '5 source feeds', icon: 'queue' } },
  { id: 's3',         type: 'storage', tone: 'emerald', position: { x: 320, y: 640 }, data: { label: 'S3 Bucket',  sub: 'PDF storage', icon: 'bucket' } },
  { id: 'scraperdb',  type: 'storage', tone: 'emerald', position: { x: 550, y: 640 }, data: { label: 'Scraper DB', sub: 'Postgres',    icon: 'db' } },

  // Orchestration lane
  { id: 'sfn',        type: 'sfn',     tone: 'violet', position: { x: 1035, y: 340 }, data: { label: 'SFN Execution', sub: 'pdf-ingestion-pipeline', icon: 'lambda' } },

  // Processing lane
  { id: 'extractor',  type: 'service', tone: 'sky',    position: { x: 1360, y: 180 }, data: { label: 'Extractor',    sub: 'ECS · v0.2.0',     icon: 'box' } },
  { id: 'classifier', type: 'service', tone: 'sky',    position: { x: 1360, y: 340 }, data: { label: 'Classifier',   sub: 'ECS · v0.2.0',     icon: 'tag' } },
  { id: 'processor',  type: 'service', tone: 'sky',    position: { x: 1360, y: 500 }, data: { label: 'Processor',    sub: 'ECS · v0.2.3',     icon: 'cog' } },

  // Commit lane
  { id: 'ingestor',   type: 'service', tone: 'teal',   position: { x: 1720, y: 340 }, data: { label: 'Ingestor',    sub: 'Commit gate',      icon: 'commit' } },
  { id: 'meddb',      type: 'storage', tone: 'emerald',position: { x: 1900, y: 180 }, data: { label: 'Medicine DB',  sub: 'Regulatory docs',  icon: 'db' } },
  { id: 'scraperdb2', type: 'storage', tone: 'emerald',position: { x: 1900, y: 500 }, data: { label: 'Scraper DB',   sub: 'Stage update',     icon: 'db' } },
]

export const SYSTEM_EDGES = [
  { id: 'e-sch-scr',  source: 'scheduler', target: 'scraper',    animated: true,  tone: 'amber' },
  { id: 'e-source-1-queue', source: 'data-source-1', target: 'source-queue', type: 'default', tone: 'amber' },
  { id: 'e-source-2-queue', source: 'data-source-2', target: 'source-queue', type: 'default', tone: 'amber' },
  { id: 'e-source-3-queue', source: 'data-source-3', target: 'source-queue', type: 'default', tone: 'amber' },
  { id: 'e-source-4-queue', source: 'data-source-4', target: 'source-queue', type: 'default', tone: 'amber' },
  { id: 'e-source-5-queue', source: 'data-source-5', target: 'source-queue', type: 'default', tone: 'amber' },
  { id: 'e-queue-scraper', source: 'source-queue', target: 'scraper', type: 'default', tone: 'amber' },
  { id: 'e-scr-s3',   source: 'scraper', target: 's3', animated: true, tone: 'amber' },
  { id: 'e-scr-db',   source: 'scraper',   target: 'scraperdb',  tone: 'amber' },
  { id: 'e-s3-sfn',   source: 's3',        target: 'sfn',        animated: true,  tone: 'violet' },
  { id: 'e-sfn-ext',  source: 'sfn',       target: 'extractor',  tone: 'sky' },
  { id: 'e-sfn-cls',  source: 'sfn',       target: 'classifier', tone: 'sky' },
  { id: 'e-sfn-prc',  source: 'sfn',       target: 'processor',  tone: 'sky' },
  { id: 'e-ext-ing',  source: 'extractor', target: 'ingestor',   tone: 'sky' },
  { id: 'e-cls-ing',  source: 'classifier',target: 'ingestor',   tone: 'sky' },
  { id: 'e-prc-ing',  source: 'processor', target: 'ingestor',   tone: 'sky' },
  { id: 'e-ing-med',  source: 'ingestor',  target: 'meddb',      animated: true,  tone: 'teal' },
  { id: 'e-ing-scdb', source: 'ingestor',  target: 'scraperdb2', animated: true,  tone: 'teal' },
]

// SFN state machine (unchanged layout, colouring via tone)
export const SFN_NODES = [
  { id: 'sfn-start',      type: 'terminal',  tone: 'slate',  position: { x: 320, y: 0   }, data: { label: 'Start', kind: 'start' } },
  { id: 'sfn-check',      type: 'sfnstate',  tone: 'violet', position: { x: 320, y: 110 }, data: { label: 'CheckHasPDFs', sub: 'Choice state', icon: 'branch' } },

  { id: 'sfn-extractor',  type: 'sfnstate',  tone: 'sky',    position: { x: 100, y: 240 }, data: { label: 'RunExtractor',  sub: 'ECS RunTask', icon: 'box' } },
  { id: 'sfn-classifier', type: 'sfnstate',  tone: 'sky',    position: { x: 540, y: 240 }, data: { label: 'RunClassifier', sub: 'ECS RunTask', icon: 'tag' } },

  { id: 'sfn-processor',  type: 'sfnstate',  tone: 'sky',    position: { x: 320, y: 380 }, data: { label: 'RunProcessor',  sub: 'ECS RunTask', icon: 'cog' } },

  { id: 'sfn-success',    type: 'sfnstate',  tone: 'emerald',position: { x: 100, y: 520 }, data: { label: 'MarkSuccess',   sub: 'Pass state', icon: 'check' } },
  { id: 'sfn-failed',     type: 'sfnstate',  tone: 'rose',   position: { x: 540, y: 520 }, data: { label: 'MarkFailed',    sub: 'Fail state', icon: 'x' } },

  { id: 'sfn-end',        type: 'terminal',  tone: 'slate',  position: { x: 320, y: 640 }, data: { label: 'End', kind: 'end' } },
]

export const SFN_EDGES = [
  { id: 's1',  source: 'sfn-start',      target: 'sfn-check',      tone: 'violet' },
  { id: 's2',  source: 'sfn-check',      target: 'sfn-extractor',  label: 'has_pdfs == true', tone: 'sky' },
  { id: 's3',  source: 'sfn-check',      target: 'sfn-classifier', label: 'default',          tone: 'sky' },
  { id: 's4',  source: 'sfn-check',      target: 'sfn-failed',     label: 'Catch #1',         tone: 'rose', dashed: true },
  { id: 's5',  source: 'sfn-extractor',  target: 'sfn-processor',  tone: 'sky' },
  { id: 's6',  source: 'sfn-classifier', target: 'sfn-processor',  tone: 'sky' },
  { id: 's7',  source: 'sfn-processor',  target: 'sfn-success',    tone: 'emerald' },
  { id: 's8',  source: 'sfn-processor',  target: 'sfn-failed',     label: 'Catch #1',         tone: 'rose', dashed: true },
  { id: 's9',  source: 'sfn-success',    target: 'sfn-end',        tone: 'emerald' },
  { id: 's10', source: 'sfn-failed',     target: 'sfn-end',        tone: 'rose' },
]

export const PANEL_DEFAULTS = { PANEL_PAD_X, PANEL_PAD_TOP, PANEL_PAD_BOTTOM }