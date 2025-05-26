"use client";

import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export type Article = {
  title: string;
  link: string;
  source: string;
  published: string; // ISO string
  caption: string;
  approval: boolean | null;
};

type GroupedArticles = Record<string, Article[]>;

const PAGE_SIZE = 3; // Number of date groups per page

function groupByDate(articles: Article[]): GroupedArticles {
  return articles.reduce((acc, article) => {
    const date = article.published.slice(0, 10); // YYYY-MM-DD
    if (!acc[date]) acc[date] = [];
    acc[date].push(article);
    return acc;
  }, {} as GroupedArticles);
}

export default function DashboardPage() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [page, setPage] = useState(0);

  useEffect(() => {
    async function fetchArticles() {
      try {
        const res = await fetch("/api/load");
        if (!res.ok) throw new Error("Failed to fetch articles");
        let data = await res.json();
        data = data.map((a: any) => ({
          ...a,
          approval: a.approval === true ? true : a.approval === false ? false : null
        }));
        setArticles(data);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    fetchArticles();
  }, []);

  // Group and sort articles by date (descending)
  const grouped = groupByDate(articles);
  const sortedDates = Object.keys(grouped).sort(
    (a, b) => new Date(b).getTime() - new Date(a).getTime()
  );
  const totalPages = Math.ceil(sortedDates.length / PAGE_SIZE);

  // Get date groups for current page
  const pageDates = sortedDates.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const updateCaption = (date: string, idx: number, newCaption: string) => {
    setArticles(prev =>
      prev.map(a =>
        a.published.slice(0, 10) === date && grouped[date][idx] === a
          ? { ...a, caption: newCaption }
          : a
      )
    );
    setSaved(false);
  };

  const toggleReject = (date: string, idx: number) => {
    setArticles(prev =>
      prev.map(a =>
        a.published.slice(0, 10) === date && grouped[date][idx] === a
          ? { ...a, approval: a.approval === false ? null : false }
          : a
      )
    );
    setSaved(false);
  };

  const toggleApprove = (date: string, idx: number) => {
    setArticles(prev =>
      prev.map(a =>
        a.published.slice(0, 10) === date && grouped[date][idx] === a
          ? { ...a, approval: a.approval === true ? null : true }
          : a
      )
    );
    setSaved(false);
  };

  const saveChanges = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ articles })
      });
      if (!res.ok) throw new Error("Failed to save");
      setSaved(true);

      await fetch("/api/dispatch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({articles}),
      });

    } catch (err) {
      console.error("❌ Save failed:", err);
      alert("Save failed.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="p-4">Loading...</p>;
  if (error) return <p className="p-4 text-red-500">Error: {error}</p>;

  return (
    <div className="p-4 space-y-4">
      {pageDates.map((date, dayIdx) => (
        <div
          key={date}
          className={`border-t pt-6 ${dayIdx > 0 ? "mt-10" : ""}`}
        >
          <div className="font-bold text-xl mb-4">{date}</div>
          <div className="space-y-4">
            {grouped[date].map((article, idx) => (
              <Card key={idx}>
                <CardContent className="space-y-2">
                  <div className="font-semibold">{article.title}</div>
                  <Textarea
                    value={article.caption}
                    onChange={e => updateCaption(date, idx, e.target.value)}
                    className="w-full"
                    rows={2}
                  />
                  <div className="flex justify-between items-center">
                    <span className="text-xs text-muted-foreground">
                      {article.published} — {article.source}
                    </span>
                    <div className="space-x-2">
                      <Button
                        variant={article.approval === true ? "default" : "outline"}
                        onClick={() => toggleApprove(date, idx)}
                      >
                        {article.approval === true ? "✅ Approved" : "Approve"}
                      </Button>
                      <Button
                        variant={article.approval === false ? "destructive" : "outline"}
                        onClick={() => toggleReject(date, idx)}
                      >
                        {article.approval === false ? "❌ Rejected" : "Reject"}
                      </Button>
                      {article.approval === null && (
                        <span className="text-xs text-muted-foreground">Pending</span>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      ))}

      <div className="flex justify-between items-center pt-4">
        <Button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}>
          Previous
        </Button>
        <span>
          Page {page + 1} of {totalPages}
        </span>
        <Button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}>
          Next
        </Button>
      </div>
      <div className="fixed bottom-0 left-0 w-full bg-white border-t py-4 flex justify-center z-50 shadow">
        <Button onClick={saveChanges} disabled={saving}>
          {saving ? "Saving..." : saved ? "✅ Saved!" : "Save Changes"}
        </Button>
      </div>
    </div>
  );
}
