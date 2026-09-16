"use client";

import Link from "next/link";
import { Radar, ArrowRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

// This page is being rebuilt into the full multi-source intelligence feed (browsing
// intelligence_items by category/agency/geography/score — see
// docs/PHASE2_ARCHITECTURE.md §11). Syncing sources now lives on the Intelligence
// Sources page (formerly a single SAM.gov-only status card here), since that's a
// Source Registry concern, not a feed-browsing one.
export default function DiscoverPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Discover</h1>
        <p className="text-sm text-muted-foreground">
          New live opportunities, pre-solicitations, early signals, and award intelligence from every connected source.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Radar className="h-4 w-4" /> Manage &amp; sync sources</CardTitle>
          <CardDescription>
            SAM.gov, USAspending.gov, Grants.gov, and every other Wave 1 source Principal tracks — enable, sync, and
            check the health of each one on the Intelligence Sources page.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/sources">
            <Button>Go to Intelligence Sources <ArrowRight className="h-4 w-4" /></Button>
          </Link>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>New Opportunities</CardTitle>
          <CardDescription>
            Newly-discovered and updated live/pre-solicitation opportunities promote automatically into the pipeline
            below — see <Link href="/opportunities" className="font-medium text-primary hover:underline">Opportunities</Link>.
            A dedicated feed here — filterable by intelligence category, agency, geography, NAICS, and score, with
            early signals and award intelligence that never enter the pipeline — is the next build on this page.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            In the meantime, use <Link href="/opportunities" className="font-medium text-primary hover:underline">New Opportunity</Link> to
            add anything you find manually — a referral, an agency forecast, or an industry-day conversation.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
