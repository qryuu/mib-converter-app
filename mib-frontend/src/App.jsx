import { useState, useRef } from 'react'
import axios from 'axios'
import './App.css'

// 言語リソース定義
const TEXT = {
  ja: {
    title: "MIB to KTranslate Converter",
    subtitle: "Metrics & Trap Profile Generator",
    loading: "処理中... (AI解析のため数分かかる場合があります)",
    step1_title: "Step 1: MIBファイルのアップロード",
    analyze_btn: "解析開始",
    step2_title: "Step 2: プロファイル設定",
    metrics_section: "Metrics (AI解説付き)",
    table_select: "選択",
    table_name: "名前",
    table_oid: "OID",
    table_desc: "AI解説 / 重要度",
    traps_section: "Traps (コメント編集可)",
    traps_hint: "Trapの通知メッセージを編集できます。空欄のままにするとAIが英語で自動生成します。",
    table_desc_edit: "Description (編集可能)",
    back_btn: "戻る",
    generate_btn: "YAMLを生成",
    step3_title: "Step 3: 生成完了",
    download_btn: "ダウンロード",
    back_to_select_btn: "選択に戻る",
    reset_btn: "最初に戻る",
    alert_no_file: "ファイルを選択してください",
    alert_error_parse: "解析に失敗しました。ファイルが正しいか確認してください。",
    alert_error_gen: "生成に失敗しました。",
    select_file_btn: "ファイルを選択",
    no_file_selected: "選択されていません",
    // ▼ 追加: YAML言語設定とプレースホルダー
    yaml_lang_label: "Pollingの解説(Description)を日本語にする (OFFの場合は英語)",
    trap_placeholder: "空欄の場合、AIが英語で自動生成します"
  },
  en: {
    title: "MIB to KTranslate Converter",
    subtitle: "Metrics & Trap Profile Generator",
    loading: "Processing... (AI analysis may take a few minutes)",
    step1_title: "Step 1: Upload MIB File",
    analyze_btn: "Start Analysis",
    step2_title: "Step 2: Profile Configuration",
    metrics_section: "Metrics (with AI Explanation)",
    table_select: "Select",
    table_name: "Name",
    table_oid: "OID",
    table_desc: "AI Desc / Importance",
    traps_section: "Traps (Editable Description)",
    traps_hint: "You can edit the Trap message. If left empty, AI will auto-generate it in English.",
    table_desc_edit: "Description (Editable)",
    back_btn: "Back",
    generate_btn: "Generate YAML",
    step3_title: "Step 3: Generation Complete",
    download_btn: "Download",
    back_to_select_btn: "Back to Selection",
    reset_btn: "Start Over",
    alert_no_file: "Please select a file.",
    alert_error_parse: "Analysis failed. Please check if the file is valid.",
    alert_error_gen: "Generation failed.",
    select_file_btn: "Choose File",
    no_file_selected: "No file selected",
    // ▼ Add: YAML Language settings and placeholder
    yaml_lang_label: "Use Japanese for Polling descriptions (Default is English)",
    trap_placeholder: "Leave empty for auto-generated English"
  }
}

function App() {
  // ★ APIのエンドポイント (必要に応じて書き換えてください)
  const API_BASE_URL = "https://rzbtaqg1t1.execute-api.ap-northeast-1.amazonaws.com"

  // 言語設定 (デフォルト: ja)
  const [lang, setLang] = useState('ja')
  const t = TEXT[lang]

  const [step, setStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [mibName, setMibName] = useState('')
  const [metrics, setMetrics] = useState([])
  const [traps, setTraps] = useState([])
  const [resultYaml, setResultYaml] = useState('')
  const [downloadUrl, setDownloadUrl] = useState('')
  const [fileName, setFileName] = useState('')
  
  // ▼ 追加: YAML内の言語設定フラグ (true=日本語, false=英語)
  const [isYamlJa, setIsYamlJa] = useState(false)

  const fileInputRef = useRef(null)

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files[0]) {
      setFileName(e.target.files[0].name)
    } else {
      setFileName('')
    }
  }

  // Step 1: ファイルアップロード & 解析
  const handleUpload = async (event) => {
    event.preventDefault()
    
    const file = fileInputRef.current?.files?.[0]
    
    if (!file) {
      alert(t.alert_no_file)
      return
    }

    setLoading(true)
    const formData = new FormData()
    formData.append('mib_file', file)
    formData.append('lang', lang)

    try {
      const res = await axios.post(`${API_BASE_URL}/parse`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      
      setMibName(res.data.mib_name)
      setMetrics(res.data.metrics.map(m => ({ ...m, checked: true })))
      setTraps(res.data.traps.map(t => ({ ...t, checked: true })))
      
      setStep(2)
    } catch (error) {
      console.error(error)
      alert(t.alert_error_parse)
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
        description: t.user_description // ユーザー入力を送信（空ならバックエンドが処理）
      })),
      // ▼ 追加: YAML言語フラグを送信
      yaml_lang: isYamlJa ? 'ja' : 'en'
    }

    try {
      const res = await axios.post(`${API_BASE_URL}/generate`, payload)
      setResultYaml(res.data.yaml_preview)
      setDownloadUrl(`${API_BASE_URL}${res.data.download_url}`)
      setStep(3)
    } catch (error) {
      console.error(error)
      alert(t.alert_error_gen)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="container">
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>{t.title}</h1>
          <p>{t.subtitle}</p>
        </div>
        
        <div className="lang-switch">
          <button 
            className={lang === 'ja' ? 'active' : ''} 
            onClick={() => setLang('ja')}
            style={{ marginRight: '5px', fontWeight: lang === 'ja' ? 'bold' : 'normal' }}
          >
            🇯🇵 JP
          </button>
          <button 
            className={lang === 'en' ? 'active' : ''} 
            onClick={() => setLang('en')}
            style={{ fontWeight: lang === 'en' ? 'bold' : 'normal' }}
          >
            🇺🇸 EN
          </button>
        </div>
      </header>

      {loading && (
        <div className="loading-overlay">
          <div className="spinner"></div>
          <p>{t.loading}</p>
        </div>
      )}

      {step === 1 && !loading && (
        <div className="card">
          <h2>{t.step1_title}</h2>
          <form onSubmit={handleUpload}>
            <div style={{ marginBottom: '15px', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <input 
                type="file" 
                required 
                accept=".mib,.my,.txt" 
                ref={fileInputRef} 
                onChange={handleFileSelect}
                style={{ display: 'none' }} 
              />
              <button 
                type="button" 
                className="secondary-btn" 
                onClick={() => fileInputRef.current.click()}
              >
                {t.select_file_btn}
              </button>
              <span style={{ color: '#666' }}>
                {fileName || t.no_file_selected}
              </span>
            </div>
            <button type="submit" className="primary-btn">{t.analyze_btn}</button>
          </form>
        </div>
      )}

      {step === 2 && !loading && (
        <div className="card full-width">
          <h2>{t.step2_title} (MIB: {mibName})</h2>
          
          <div className="section">
            <h3>{t.metrics_section}</h3>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>{t.table_select}</th>
                    <th>{t.table_name}</th>
                    <th>{t.table_oid}</th>
                    <th>{t.table_desc}</th>
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
            <h3>{t.traps_section}</h3>
            <p className="hint">{t.traps_hint}</p>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>{t.table_select}</th>
                    <th>{t.table_name}</th>
                    <th>{t.table_oid}</th>
                    <th>{t.table_desc_edit}</th>
                  </tr>
                </thead>
                <tbody>
                  {traps.map((t, i) => (
                    <tr key={i} className={t.checked ? '' : 'dimmed'}>
                      <td><input type="checkbox" checked={t.checked} onChange={() => toggleTrap(i)} /></td>
                      <td>{t.name}</td>
                      <td>{t.oid}</td>
                      <td>
                        {/* ▼ 修正: プレースホルダーにAI自動生成の注記を追加 */}
                        <textarea 
                          className="trap-input"
                          value={t.user_description || ''} 
                          onChange={(e) => handleTrapDescChange(i, e.target.value)}
                          placeholder={t.trap_placeholder}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="actions" style={{ flexDirection: 'column', gap: '15px' }}>
            {/* ▼ 追加: YAML言語設定チェックボックス */}
            <div style={{ alignSelf: 'flex-end', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input 
                type="checkbox" 
                id="yamlLangToggle" 
                checked={isYamlJa} 
                onChange={(e) => setIsYamlJa(e.target.checked)} 
                style={{ cursor: 'pointer', width: '18px', height: '18px' }}
              />
              <label htmlFor="yamlLangToggle" style={{ cursor: 'pointer', userSelect: 'none' }}>
                {t.yaml_lang_label}
              </label>
            </div>

            <div style={{ display: 'flex', gap: '10px', width: '100%', justifyContent: 'flex-end' }}>
              <button onClick={() => setStep(1)} className="secondary-btn">{t.back_btn}</button>
              <button onClick={handleGenerate} className="primary-btn">{t.generate_btn}</button>
            </div>
          </div>
        </div>
      )}

      {step === 3 && !loading && (
        <div className="card">
          <h2>{t.step3_title}</h2>
          <textarea className="yaml-preview" readOnly value={resultYaml} />
          <div className="actions">
            <a href={downloadUrl} download={`${mibName}_profile.yaml`}>
              <button className="primary-btn">{t.download_btn}</button>
            </a>
            
            <button onClick={() => setStep(2)} className="secondary-btn">{t.back_to_select_btn}</button>
            <button onClick={() => setStep(1)} className="secondary-btn">{t.reset_btn}</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default App