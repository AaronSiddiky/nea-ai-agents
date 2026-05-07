"use client";

import { useState, useCallback, useId } from "react";
import { useAuth } from "@clerk/nextjs";
import { generateOutreach, submitOutreachFeedback, type OutreachResponse } from "@/lib/api";

const INVESTORS = [
  { key: "ashley",   name: "Ashley Jepson",  role: "Investor — Data/AI Infra" },
  { key: "tiffany",  name: "Tiffany",         role: "Investor — B2B SaaS & AI" },
  { key: "danielle", name: "Danielle",        role: "Partner — Consumer" },
  { key: "madison",  name: "Madison",         role: "Partner — Former Meta AI Researcher" },
  { key: "alexa",    name: "Alexa Grabelle",  role: "Associate — Technology" },
  { key: "andrew",   name: "Andrew Schoen",   role: "Partner — AI/Security/Deep Tech" },
  { key: "maanasi",  name: "Maanasi",         role: "Associate — AI Infrastructure" },
];

const CTX_TYPES = [
  { value: "",                              label: "Auto-detect" },
  { value: "thesis_driven_deep_dive",       label: "Thesis-driven deep dive" },
  { value: "problem_solving_discussion",    label: "Problem-solving discussion" },
  { value: "founder_background_connection", label: "Founder background connection" },
  { value: "stealth_founder_outreach",      label: "Stealth founder outreach" },
];

const inputCls = "w-full px-3 py-2 rounded-lg border border-zinc-300 text-sm text-zinc-900 placeholder:text-zinc-400 bg-white focus:outline-none focus:ring-2 focus:ring-nea-blue/20 focus:border-nea-blue transition-colors";
const labelCls = "block text-xs font-medium text-zinc-700 mb-1.5";

export default function OutreachPage() {
  const { getToken } = useAuth();
  const fid = useId();
  const [company, setCompany]       = useState("");
  const [investor, setInvestor]     = useState("ashley");
  const [format, setFormat]         = useState<"email" | "linkedin">("email");
  const [contact, setContact]       = useState("");
  const [ctx, setCtx]               = useState("");
  const [advanced, setAdvanced]     = useState(false);
  const [skipIngest, setSkipIngest] = useState(false);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState<string | null>(null);
  const [result, setResult]         = useState<OutreachResponse | null>(null);
  const [fbMode, setFbMode]         = useState<"idle" | "editing" | "done">("idle");
  const [edited, setEdited]         = useState("");
  const [fbBusy, setFbBusy]         = useState(false);
  const [copied, setCopied]         = useState(false);

  const handleGenerate = useCallback(async () => {
    const t = company.trim(); if (!t) return;
    setLoading(true); setError(null); setResult(null); setFbMode("idle");
    try {
      const r = await generateOutreach({
        company_id: t,
        investor_key: investor,
        output_format: format,
        contact_name: contact.trim() || undefined,
        context_type_override: ctx || undefined,
        skip_ingest: skipIngest,
      }, getToken);
      setResult(r); setEdited(r.message ?? "");
    } catch (e) { setError(e instanceof Error ? e.message : "Generation failed"); }
    finally { setLoading(false); }
  }, [company, investor, format, contact, ctx, skipIngest, getToken]);

  const handleFeedback = useCallback(async (status: "approved" | "edited" | "rejected") => {
    if (!result) return;
    setFbBusy(true);
    try {
      await submitOutreachFeedback({
        outreach_id: result.company_id + "_" + result.investor_key + "_" + Date.now(),
        investor_key: result.investor_key,
        company_id: result.company_id,
        context_type: result.context_type ?? undefined,
        original_message: result.message ?? "",
        edited_message: status === "edited" ? edited : undefined,
        approval_status: status,
      }, getToken);
      setFbMode("done");
    } catch (e) { setError(e instanceof Error ? e.message : "Feedback failed"); }
    finally { setFbBusy(false); }
  }, [result, edited, getToken]);

  const copyEmail = useCallback(() => {
    const txt = result?.subject ? "Subject: " + result.subject + "\n\n" + result.message : result?.message ?? "";
    navigator.clipboard.writeText(txt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [result]);

  const openInOutlook = useCallback(() => {
    const body = fbMode === "editing" ? edited : (result?.message ?? "");
    const subject = result?.subject ?? "";
    const url =
      "https://outlook.office.com/mail/deeplink/compose" +
      "?subject=" + encodeURIComponent(subject) +
      "&body=" + encodeURIComponent(body);
    window.open(url, "_blank", "noopener,noreferrer");
  }, [result, fbMode, edited]);

  const selInv = INVESTORS.find(i => i.key === investor);

  return (
    <div className="flex h-full">

      {/* Config panel */}
      <div className="w-64 shrink-0 border-r border-zinc-200 bg-zinc-50 overflow-y-auto flex flex-col">
        <div className="h-14 px-5 border-b border-zinc-200 bg-white flex items-center shrink-0">
          <h1 className="text-sm font-semibold text-zinc-900">Outreach</h1>
        </div>

        <div className="flex-1 px-4 py-5 space-y-5">

          <div>
            <label htmlFor={fid + "-co"} className={labelCls}>Company Domain</label>
            <input
              id={fid + "-co"}
              type="text"
              placeholder="distyl.ai"
              value={company}
              onChange={e => setCompany(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleGenerate()}
              className={inputCls}
            />
          </div>

          <div>
            <label htmlFor={fid + "-inv"} className={labelCls}>Investor Voice</label>
            <select
              id={fid + "-inv"}
              value={investor}
              onChange={e => setInvestor(e.target.value)}
              className={inputCls}
            >
              {INVESTORS.map(inv => <option key={inv.key} value={inv.key}>{inv.name}</option>)}
            </select>
            {selInv && <p className="text-[11px] text-zinc-400 mt-1">{selInv.role}</p>}
          </div>

          <div>
            <label className={labelCls}>Format</label>
            <div className="flex rounded-lg border border-zinc-300 overflow-hidden">
              {(["email", "linkedin"] as const).map(f => (
                <button key={f} onClick={() => setFormat(f)}
                  className={`flex-1 py-2 text-sm font-medium transition-colors ${
                    format === f ? "bg-nea-blue text-white" : "text-zinc-500 hover:bg-zinc-50 bg-white"
                  }`}>
                  {f === "email" ? "Email" : "LinkedIn"}
                </button>
              ))}
            </div>
          </div>

          {/* Advanced toggle */}
          <div>
            <button
              onClick={() => setAdvanced(v => !v)}
              className="flex items-center gap-1.5 text-xs font-medium text-zinc-400 hover:text-zinc-600 transition-colors"
            >
              <svg className={`w-3 h-3 transition-transform ${advanced ? "rotate-90" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
              Advanced options
            </button>
            {advanced && (
              <div className="mt-3 space-y-3 pl-3 border-l-2 border-zinc-200">
                <div>
                  <label className={labelCls}>Contact Name</label>
                  <input
                    type="text"
                    placeholder="Patrick Collison"
                    value={contact}
                    onChange={e => setContact(e.target.value)}
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className={labelCls}>Context Type</label>
                  <select value={ctx} onChange={e => setCtx(e.target.value)} className={inputCls}>
                    {CTX_TYPES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                  </select>
                </div>
                <label className="flex items-center gap-2 cursor-pointer text-xs text-zinc-500">
                  <input type="checkbox" checked={skipIngest} onChange={e => setSkipIngest(e.target.checked)}
                    className="rounded border-zinc-300" />
                  Use cached company data
                </label>
              </div>
            )}
          </div>

          <button
            onClick={handleGenerate}
            disabled={loading || !company.trim()}
            className="w-full py-2 rounded-lg bg-nea-blue text-white text-sm font-semibold hover:bg-nea-blue-dark disabled:opacity-40 transition-colors"
          >
            {loading ? "Generating…" : "Run Outreach"}
          </button>

        </div>
      </div>

      {/* Result panel */}
      <div className="flex-1 overflow-y-auto px-7 py-6">

        {!result && !loading && !error && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-center">
            <div className="w-10 h-10 rounded-xl bg-zinc-100 border border-zinc-200 flex items-center justify-center mb-2">
              <svg className="w-5 h-5 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <p className="text-sm text-zinc-500">Configure and run outreach on the left</p>
          </div>
        )}

        {error && (
          <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700 mb-5">{error}</div>
        )}

        {loading && (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <div className="w-5 h-5 border-2 border-zinc-200 border-t-nea-blue rounded-full animate-spin" />
            <p className="text-sm text-zinc-400">Generating outreach — about 20 seconds</p>
          </div>
        )}

        {result && !loading && (
          <div className="max-w-2xl">

            {/* Meta */}
            <div className="mb-5">
              <div className="flex items-center gap-2 flex-wrap min-w-0 mb-1">
                <span className="text-lg font-semibold text-zinc-900 break-words">{result.company_name}</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-nea-blue text-white font-medium">
                  {selInv?.name ?? result.investor_key}
                </span>
                {result.context_type && (
                  <span className="text-xs px-2 py-0.5 rounded-full border border-zinc-200 text-zinc-400">
                    {result.context_type.replace(/_/g, " ")}
                  </span>
                )}
              </div>
              {result.contact_name && (
                <div className="flex items-center gap-1.5 text-xs text-zinc-400 min-w-0">
                  <span>To: {result.contact_name}{result.contact_title ? ` (${result.contact_title})` : ""}</span>
                  {result.contact_linkedin && (
                    <a href={result.contact_linkedin} target="_blank" rel="noopener noreferrer"
                      className="text-zinc-300 hover:text-nea-blue shrink-0 transition-colors">
                      <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" />
                      </svg>
                    </a>
                  )}
                </div>
              )}
            </div>

            {/* Message card */}
            <div className="bg-white rounded-xl border border-zinc-200 overflow-hidden mb-4">
              {result.subject && (
                <div className="px-5 py-3 border-b border-zinc-100 bg-zinc-50 flex items-baseline gap-2">
                  <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wide shrink-0">Subject</span>
                  <span className="text-sm font-semibold text-zinc-900 min-w-0 break-words">{result.subject}</span>
                </div>
              )}
              {fbMode === "editing"
                ? <textarea
                    value={edited}
                    onChange={e => setEdited(e.target.value)}
                    className="w-full px-5 py-4 text-sm text-zinc-800 leading-relaxed focus:outline-none resize-none"
                    rows={18}
                  />
                : <div className="px-5 py-4 text-sm text-zinc-800 leading-relaxed whitespace-pre-wrap">{result.message}</div>
              }
            </div>

            {/* Actions */}
            {fbMode === "done" ? (
              <div className="flex items-center gap-2 text-sm text-green-600 font-medium">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Feedback saved
              </div>
            ) : (
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={copyEmail}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-zinc-200 text-xs font-medium text-zinc-500 hover:border-zinc-300 hover:text-zinc-700 transition-colors">
                  {copied ? "✓ Copied" : "Copy"}
                </button>
                {format === "email" && (
                  <button onClick={openInOutlook}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-zinc-200 text-xs font-medium text-zinc-500 hover:border-zinc-300 hover:text-zinc-700 transition-colors">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                    </svg>
                    Open in Outlook
                  </button>
                )}
                <div className="flex items-center gap-1.5 ml-auto">
                  {fbMode === "editing" ? (
                    <>
                      <button onClick={() => setFbMode("idle")}
                        className="px-3 py-1.5 rounded-lg border border-zinc-200 text-xs font-medium text-zinc-500 hover:bg-zinc-50 transition-colors">
                        Cancel
                      </button>
                      <button onClick={() => handleFeedback("edited")} disabled={fbBusy}
                        className="px-4 py-1.5 rounded-lg bg-nea-blue text-white text-xs font-semibold hover:bg-nea-blue-dark disabled:opacity-40 transition-colors">
                        {fbBusy ? "Saving…" : "Save Edit"}
                      </button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => setFbMode("editing")}
                        className="px-3 py-1.5 rounded-lg border border-zinc-200 text-xs font-medium text-zinc-500 hover:bg-zinc-50 transition-colors">
                        Edit
                      </button>
                      <button onClick={() => handleFeedback("approved")} disabled={fbBusy}
                        className="px-3 py-1.5 rounded-lg bg-green-50 text-green-700 border border-green-200 text-xs font-semibold hover:bg-green-100 disabled:opacity-40 transition-colors">
                        Approve
                      </button>
                      <button onClick={() => handleFeedback("rejected")} disabled={fbBusy}
                        className="px-3 py-1.5 rounded-lg bg-red-50 text-red-600 border border-red-200 text-xs font-semibold hover:bg-red-100 disabled:opacity-40 transition-colors">
                        Reject
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}

          </div>
        )}
      </div>
    </div>
  );
}
