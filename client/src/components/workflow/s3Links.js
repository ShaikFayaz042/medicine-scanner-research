// Bucket + prefix observed from backend ECS command overrides.
// If it changes, update this constant (or wire to import.meta.env.VITE_S3_BUCKET).
const BUCKET = 'medicine-data-storage-449902674528-ap-south-1-an'
const PREFIX_ROOT = 'medicine-data-storage/processed_files/runs'

export function s3ConsoleUrl(prefix, region = 'ap-south-1') {
  return `https://s3.console.aws.amazon.com/s3/buckets/${BUCKET}?region=${region}&prefix=${encodeURIComponent(prefix)}`
}

const NODE_ARTIFACTS = {
  extractor:         [{ label: 'Extracted JSON',  suffix: 'extracted_json' }],
  classifier:        [{ label: 'Classified JSON', suffix: 'classified_json' }],
  processor:         [
    { label: 'Parsed JSON',     suffix: 'parsed_json' },
    { label: 'Normalized JSON', suffix: 'normalized_json' },
  ],
  'sfn-extractor':   [{ label: 'Extracted JSON',  suffix: 'extracted_json' }],
  'sfn-classifier':  [{ label: 'Classified JSON', suffix: 'classified_json' }],
  'sfn-processor':   [
    { label: 'Parsed JSON',     suffix: 'parsed_json' },
    { label: 'Normalized JSON', suffix: 'normalized_json' },
  ],
}

export function getNodeArtifacts(nodeId, runId, region = 'ap-south-1') {
  if (!runId) return []
  const list = NODE_ARTIFACTS[nodeId] || []
  const base = `${PREFIX_ROOT}/${runId}`
  return list.map(({ label, suffix }) => ({
    label,
    prefix: `${base}/${suffix}`,
    url: s3ConsoleUrl(`${base}/${suffix}`, region),
  }))
}

export function getManifestLink(runId, region = 'ap-south-1') {
  if (!runId) return null
  const key = `${PREFIX_ROOT}/${runId}/manifest.json`
  return { label: 'manifest.json', prefix: key, url: s3ConsoleUrl(key, region) }
}