"use client";

import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export type Article = {
  title: string;
  link: string;
  source: string;
  published: string;
  caption: string;
  approved: boolean;
};

export default function DashboardPage() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    async function fetchArticles() {
      try {
        const res = await fetch("/api/load");
        if (!res.ok) throw new Error("Failed to fetch articles");
        const data = await res.json();
        setArticles(data);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }

    fetchArticles();
  }, []);

  const updateCaption = (index: number, newCaption: string) => {
    setArticles(prev => {
      const updated = [...prev];
      updated[index].caption = newCaption;
      return updated;
    });
  };

  const toggleApproval = (index: number) => {
    setArticles(prev => {
      const updated = [...prev];
      updated[index].approved = !updated[index].approved;
      return updated;
    });
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

      // Trigger GitHub Action to regenerate RSS
      await fetch("https://api.github.com/repos/tblarel/inyourbones/actions/workflows/rss_regen.yml/dispatches", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${process.env.NEXT_PUBLIC_GITHUB_PAT}`,
          "Accept": "application/vnd.github+json",
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ ref: "main" })
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
      {articles.map((article, index) => (
        <Card key={index}>
          <CardContent className="space-y-2">
            <div className="font-semibold">{article.title}</div>
            <Textarea
              value={article.caption}
              onChange={e => updateCaption(index, e.target.value)}
              className="w-full"
              rows={2}
            />
            <div className="flex justify-between items-center">
              <span className="text-xs text-muted-foreground">
                {article.published} — {article.source}
              </span>
              <Button
                variant={article.approved ? "default" : "outline"}
                onClick={() => toggleApproval(index)}
              >
                {article.approved ? "Approved ✅" : "Approve"}
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
      <div className="text-center pt-4">
        <Button onClick={saveChanges} disabled={saving}>
          {saving ? "Saving..." : saved ? "✅ Saved!" : "Save Changes"}
        </Button>
      </div>
    </div>
  );
}
