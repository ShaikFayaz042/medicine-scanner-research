export function buildS3Link(path) {
  if (!path) return null
  return `/static-pdf/${encodeURIComponent(path)}`
}

export default buildS3Link
