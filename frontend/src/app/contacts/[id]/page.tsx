"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { contactsApi } from "@/lib/api/resources";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingState, ErrorState } from "@/components/ui/states";
import { formatDate, titleCase } from "@/lib/utils";
import type { Contact } from "@/types";

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm text-foreground">{value || "—"}</div>
    </div>
  );
}

export default function ContactDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [contact, setContact] = useState<Contact | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    contactsApi.get(id).then(setContact).catch((e) => setError(e.message));
  }
  useEffect(load, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!contact) return <LoadingState />;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold text-foreground">{contact.full_name}</h1>
        <div className="mt-1 flex items-center gap-2">
          <Badge variant="outline">{titleCase(contact.role)}</Badge>
          {contact.relationship_strength && <Badge variant="accent">Relationship {contact.relationship_strength}/5</Badge>}
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>Contact Details</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <Fact label="Organization" value={contact.organization} />
          <Fact label="Title" value={contact.title} />
          <Fact label="Email" value={contact.email} />
          <Fact label="Phone" value={contact.phone} />
          <Fact label="Last Contact" value={formatDate(contact.last_contact_date)} />
          <Fact label="Next Follow-up" value={formatDate(contact.next_follow_up_date)} />
        </CardContent>
        {contact.notes && (
          <CardContent className="border-t border-border pt-4">
            <Fact label="Notes" value={contact.notes} />
          </CardContent>
        )}
      </Card>
    </div>
  );
}
