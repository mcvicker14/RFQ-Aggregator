"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Download, FileText, Sparkles, Upload } from "lucide-react";
import { documentsApi } from "@/lib/api/resources";
import { ApiClientError } from "@/lib/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState, LoadingState } from "@/components/ui/states";
import { formatDate, titleCase } from "@/lib/utils";
import type { AiSolicitationAnalysis, OpportunityDocument } from "@/types";

const CATEGORIES = [
  "solicitation", "amendment", "scope", "plans", "agency_document", "proposal_draft", "sf330",
  "teaming_agreement", "resume", "project_sheet", "debrief", "award_document", "other",
];

export function DocumentsTab({ opportunityId }: { opportunityId: string }) {
  const [documents, setDocuments] = useState<OpportunityDocument[] | null>(null);
  const [category, setCategory] = useState("solicitation");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [analyses, setAnalyses] = useState<Record<string, AiSolicitationAnalysis | "not_configured" | "none">>({});
  const [analyzing, setAnalyzing] = useState<string | null>(null);

  function load() {
    documentsApi.list(opportunityId).then(setDocuments).catch(() => setDocuments([]));
  }
  useEffect(load, [opportunityId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      await documentsApi.upload(opportunityId, file, category);
      load();
    } catch (err) {
      setUploadError(err instanceof ApiClientError ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function runAnalysis(documentId: string) {
    setAnalyzing(documentId);
    try {
      const result = await documentsApi.analyze(documentId);
      setAnalyses((prev) => ({ ...prev, [documentId]: result }));
    } catch (err) {
      if (err instanceof ApiClientError && err.status === 503) {
        setAnalyses((prev) => ({ ...prev, [documentId]: "not_configured" }));
      } else {
        setAnalyses((prev) => ({ ...prev, [documentId]: "none" }));
      }
    } finally {
      setAnalyzing(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle>Document Repository</CardTitle>
        <div className="flex items-center gap-2">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
            <SelectContent>
              {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{titleCase(c)}</SelectItem>)}
            </SelectContent>
          </Select>
          <input ref={fileInputRef} type="file" onChange={handleUpload} className="hidden" id="doc-upload" />
          <Button size="sm" disabled={uploading} onClick={() => fileInputRef.current?.click()}>
            <Upload className="h-3.5 w-3.5" /> {uploading ? "Uploading…" : "Upload"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {uploadError && (
          <p className="flex items-center gap-1.5 text-xs text-destructive"><AlertTriangle className="h-3.5 w-3.5" /> {uploadError}</p>
        )}
        {!documents ? (
          <LoadingState />
        ) : documents.length === 0 ? (
          <EmptyState
            title="No documents uploaded yet"
            description="Upload the RFP, RFQ, Sources Sought notice, or SOW to build the document record and enable AI analysis."
          />
        ) : (
          <div className="flex flex-col gap-3">
            {documents.map((doc) => {
              const analysis = analyses[doc.id];
              return (
                <div key={doc.id} className="rounded-md border border-border p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                      <div>
                        <div className="text-sm font-medium text-foreground">{doc.original_filename}</div>
                        <div className="text-xs text-muted-foreground">{titleCase(doc.category)} · {formatDate(doc.created_at)}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <a href={documentsApi.downloadUrl(doc.id)} target="_blank" rel="noreferrer">
                        <Button size="sm" variant="outline"><Download className="h-3.5 w-3.5" /> Download</Button>
                      </a>
                      <Button size="sm" variant="outline" disabled={analyzing === doc.id} onClick={() => runAnalysis(doc.id)}>
                        <Sparkles className="h-3.5 w-3.5" /> {analyzing === doc.id ? "Analyzing…" : "Analyze with AI"}
                      </Button>
                    </div>
                  </div>

                  {analysis === "not_configured" && (
                    <div className="mt-3 rounded-md bg-warning/10 p-3 text-xs text-warning">
                      AI solicitation analysis is not configured for this deployment. An administrator needs to add an
                      Anthropic API key (ANTHROPIC_API_KEY) to the backend environment — see backend/.env.example.
                    </div>
                  )}
                  {analysis === "none" && (
                    <div className="mt-3 rounded-md bg-destructive/10 p-3 text-xs text-destructive">
                      AI analysis failed for this document. Try again, or confirm the file is a supported PDF/DOCX/TXT.
                    </div>
                  )}
                  {analysis && typeof analysis === "object" && <AnalysisResult analysis={analysis} />}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AnalysisResult({ analysis }: { analysis: AiSolicitationAnalysis }) {
  return (
    <div className="mt-3 flex flex-col gap-3 rounded-md border border-border bg-secondary/40 p-3 text-sm">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Executive Summary</div>
        <p className="mt-1 text-foreground">{analysis.executive_summary}</p>
      </div>
      {analysis.top_10_things_to_know && analysis.top_10_things_to_know.length > 0 && (
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Top Things to Know</div>
          <ol className="mt-1 list-decimal space-y-0.5 pl-4 text-foreground">
            {analysis.top_10_things_to_know.map((item, i) => <li key={i}>{item}</li>)}
          </ol>
        </div>
      )}
      {analysis.red_flags && analysis.red_flags.length > 0 && (
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-destructive">Potential Red Flags</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-foreground">
            {analysis.red_flags.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </div>
      )}
      <p className="text-[11px] text-muted-foreground">
        AI-extracted from the uploaded document (model: {analysis.model_used}). Verify against the source before relying
        on it for a proposal decision.
      </p>
    </div>
  );
}
