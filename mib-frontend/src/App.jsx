import { useState, useRef } from 'react'
import axios from 'axios'
import './App.css'

function App() {
  // あなたのAPI Gatewayのエンドポイント
  // ※ もしここが変わっている場合は、あなたの正しいURLに書き換えてください
  const API_BASE_URL = "https://rzbtaqg1t1.execute-api.ap-northeast-1.amazonaws.com"

  const [step, setStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [mibName, setMibName] = useState('')
  const [metrics, setMetrics] = useState([])
  const [traps, setTraps] = useState([])
  const [resultYaml, setResultYaml] = useState('')
  const [downloadUrl, setDownloadUrl] = useState('')

  // ファイル入力への参照
  const fileInputRef = useRef(null)

  // Step 1: ファイルアップロード & 解析
  const handleUpload = async (event) => {
    event.preventDefault()
    
    // useRef を使って確実にファイルを取得
    const file = fileInputRef.current?.files?.[0]
    
    if (!file) {
      alert("ファイルを選択してください")
      return
    }

    setLoading(true)
    const formData = new FormData()
    formData.append('mib_file', file)
    formData.append('lang', 'ja')

    try {
      const res = await axios.post(`${API_BASE_URL}/parse`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      
      setMibName(res.data.mib_name)
      // 選択状態を管理するため、checkedプロパティを追加
      setMetrics(res.data.metrics.map(m => ({ ...m, checked: true })))
      setTraps(res.data.traps.map(t => ({ ...t, checked: true })))
      
      setStep(2)
    } catch (error) {
      console.error(error)
      alert("解析に失敗しました。ファイルが正しいか、またはAPIが起動しているか確認してください。")
    } finally {
      setLoading(false)
    }
  }

  // Trapの説明文を編集するハンドラ
  const handleTrapDescChange = (index, newDesc) => {
    const newTraps = [...traps]
    newTraps[index].user_description = newDesc
    setTraps(newTraps)
  }

  // チェックボックスの切り替え
  const toggleMetric = (index) => {
    const newMetrics = [...metrics]
    newMetrics[index].checked = !newMetrics[index].checked
    setMetrics(newMetrics)
  }
  
  const toggleTrap = (index) => {
    const newTraps = [...traps]
    newTraps[index].checked = !newTraps[index].checked
    setTraps(newTraps)
  }

  // Step 2: 生成リクエスト
  const handleGenerate = async () => {
    setLoading(true)
    
    const payload = {
      mib_name: mibName,
      metrics: metrics.filter(m => m.checked),
      traps: traps.filter(t => t.checked).map(t => ({
        name: t.name,
        oid: t.oid,
        description: t.user_description
      }))
    }

    try {
      const res = await axios.post(`${API_BASE_URL}/generate`, payload)
      setResultYaml(res.data.yaml_preview)
      setDownloadUrl(`${API_BASE_URL}${res.data.download_url}`)
      setStep(3)
    } catch (error) {
      console.error(error)
      alert("生成に失敗しました。")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="container">
      <header>
        <h1>MIB to KTranslate Converter</h1>
        <p>Metrics & Trap Profile Generator</p>
      </header>

      {loading && (
        <div className="loading-overlay">
          <div className="spinner"></div>
          <p>処理中... (AI解析のため数分かかる場合があります)</p>
        </div>
      )}

      {step === 1 && !loading && (
        <div className="card">
          <h2>Step 1: MIBファイルのアップロード</h2>
          <form onSubmit={handleUpload}>
            <input 
              type="file" 
              required 
              accept=".mib,.my,.txt" 
              ref={fileInputRef} 
            />
            <button type="submit" className="primary-btn">解析開始</button>
          </form>
        </div>
      )}

      {step === 2 && !loading && (
        <div className="card full-width">
          <h2>Step 2: プロファイル設定 (MIB: {mibName})</h2>
          
          <div className="section">
            <h3>Metrics (AI解説付き)</h3>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>選択</th>
                    <th>名前</th>
                    <th>OID</th>
                    <th>AI解説 / 重要度</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.map((m, i) => (
                    <tr key={i} className={m.checked ? '' : 'dimmed'}>
                      <td><input type="checkbox" checked={m.checked} onChange={() => toggleMetric(i)} /></td>
                      <td>{m.name}</td>
                      <td>{m.oid}</td>
                      <td>
                        <span className={`badge ${m.importance === 'High' ? 'high' : 'low'}`}>
                          {m.importance}
                        </span>
                        <br/>{m.ai_desc}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="section">
            <h3>Traps (コメント編集可)</h3>
            <p className="hint">Trapの通知メッセージ(Description)を自由に編集できます。</p>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>選択</th>
                    <th>名前</th>
                    <th>OID</th>
                    <th>Description (編集可能)</th>
                  </tr>
                </thead>
                <tbody>
                  {traps.map((t, i) => (
                    <tr key={i} className={t.checked ? '' : 'dimmed'}>
                      <td><input type="checkbox" checked={t.checked} onChange={() => toggleTrap(i)} /></td>
                      <td>{t.name}</td>
                      <td>{t.oid}</td>
                      <td>
                        <textarea 
                          className="trap-input"
                          value={t.user_description} 
                          onChange={(e) => handleTrapDescChange(i, e.target.value)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="actions">
            <button onClick={() => setStep(1)} className="secondary-btn">戻る</button>
            <button onClick={handleGenerate} className="primary-btn">YAMLを生成</button>
          </div>
        </div>
      )}

      {step === 3 && !loading && (
        <div className="card">
          <h2>Step 3: 生成完了</h2>
          <textarea className="yaml-preview" readOnly value={resultYaml} />
          <div className="actions">
            <a href={downloadUrl} download={`${mibName}_profile.yaml`}>
              <button className="primary-btn">ダウンロード</button>
            </a>
            
            {/* ▼▼▼ 追加したボタン ▼▼▼ */}
            <button onClick={() => setStep(2)} className="secondary-btn">選択に戻る</button>
            {/* ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲ */}

            <button onClick={() => setStep(1)} className="secondary-btn">最初に戻る</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default App