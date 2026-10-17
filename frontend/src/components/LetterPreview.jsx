// Read-only preview of a letter, drawn from the stored letter model (approximate:
// fonts and spacing may differ slightly from Word; the .docx is the real document).

const PARTS = /(\*\*.+?\*\*|\[\[MISSING:\s*[^\]]+?\s*\]\])/g

function RichText({ text }) {
  if (!text) return null
  return text.split(PARTS).map((piece, i) => {
    const missing = piece.match(/^\[\[MISSING:\s*(.+?)\s*\]\]$/)
    if (missing) return <mark key={i} className="missing">[{missing[1]} — to be filled]</mark>
    const bold = piece.match(/^\*\*(.+)\*\*$/)
    if (bold) return <strong key={i}>{bold[1]}</strong>
    return <span key={i}>{piece}</span>
  })
}

function formatApproval(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'long', year: 'numeric' }).format(
    new Date(value),
  )
}

export default function LetterPreview({ letter }) {
  const { content, letterhead } = letter
  return (
    <div className="paper" aria-label={`Letter ${letter.demand_code}, version ${letter.version_no}`}>
      {letterhead ? (
        <img className="paper-band" src={`/api/v1/files/${letterhead.header_file_id}`} alt="Letterhead header" />
      ) : (
        <div className="paper-band-missing">No letterhead on this version</div>
      )}
      <div className="paper-meta">
        <span>
          <strong>Demand Order ID :</strong> <span className="paper-code">{letter.demand_code}</span>
        </span>
        <span>
          <strong>Date :</strong> {formatApproval(letter.approved_at)}
        </span>
      </div>
      {letter.lifecycle !== 'approved' && <div className="paper-draft">DRAFT — NOT APPROVED</div>}
      <div className="paper-body">
        {content.title && (
          <h2 className="paper-title">
            <RichText text={content.title} />
          </h2>
        )}
        {content.blocks.map((b, i) => {
          if (b.type === 'heading') {
            const Tag = b.level === 1 ? 'h3' : 'h4'
            return (
              <Tag key={i} className="paper-heading">
                <RichText text={b.text} />
              </Tag>
            )
          }
          if (b.type === 'paragraph')
            return (b.text || '').split('\n').map((line, j) => (
              <p key={`${i}-${j}`}>
                <RichText text={line} />
              </p>
            ))
          if (b.type === 'bullets')
            return (
              <ul key={i}>
                {b.items.map((item, j) => (
                  <li key={j}>
                    <RichText text={item} />
                  </li>
                ))}
              </ul>
            )
          if (b.type === 'table')
            return (
              <div key={i} className="paper-table-wrap">
                <table className="paper-table">
                  {b.columns?.some((c) => c.trim()) && (
                    <thead>
                      <tr>
                        {b.columns.map((c, j) => (
                          <th key={j}>
                            <RichText text={c} />
                          </th>
                        ))}
                      </tr>
                    </thead>
                  )}
                  <tbody>
                    {b.rows.map((row, r) => (
                      <tr key={r}>
                        {row.map((cell, c) => (
                          <td key={c}>
                            <RichText text={cell} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          if (b.type === 'image') {
            const fileId = b.image_id?.split('-')[1]
            return (
              <figure key={i} className="paper-figure">
                <img src={`/api/v1/files/${fileId}`} alt={b.caption || 'Image from the JD'} />
                {b.caption && (
                  <figcaption>
                    <RichText text={b.caption} />
                  </figcaption>
                )}
              </figure>
            )
          }
          return null
        })}
      </div>
      {letterhead && <img className="paper-band" src={`/api/v1/files/${letterhead.footer_file_id}`} alt="Letterhead footer" />}
    </div>
  )
}
