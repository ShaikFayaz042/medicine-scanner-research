export function SearchBar({ value = '', onChange, placeholder = 'Search...' }) {
  return (
    <label className="filter-search">
      <input
        aria-label="Search"
        value={value}
        onChange={onChange}
        placeholder={placeholder}
      />
    </label>
  )
}

export default SearchBar
