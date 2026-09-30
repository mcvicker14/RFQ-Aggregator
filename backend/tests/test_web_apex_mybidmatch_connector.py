"""Regression tests for the live MyBidMatch structure and exact FSG C gate.

Fixtures retain the observed HTML shape, with subscriber identifiers removed.
No production database or source network access is used by these tests.
"""
from datetime import date, datetime, timezone
import httpx
import pytest
from app.connectors import web_apex_mybidmatch as m
from app.models.enums import IntelligenceCategory

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
INDEX = '''<table><tr><td>Date</td><td>Articles</td><td>Read</td></tr>
<tr><td><a href="/go?doc=day1">Tuesday, Sep 29, 2026</a></td><td>6</td><td>New</td></tr></table>'''
HEADER = '<tr><td>#</td><td>Source</td><td>Agency</td><td>FSG</td><td>Title</td><td>Keywords</td></tr>'
def row(fsg='C', seq=1, source='procure'):
    return f'<tr><td>{seq}</td><td>{source}</td><td>DEPT OF DEFENSE</td><td>{fsg}</td><td><a href="/article?doc=day1&amp;seq={seq}">$499M AE General Services MATOC</a></td><td>naics!541330;</td></tr>'
DAILY = '<table>' + HEADER + ''.join(row(fsg, i) for i,fsg in enumerate(['C','Y','C219','','c','C'],1)) + '</table>'
ARTICLE = '''<div class="art-box"><div class="noprint">Sep 29, 2026 navigation</div>
<h4>DEPT OF DEFENSE, TULSA OK 74137</h4>
<p>C -- $499M AE General Services MATOC SOL W912BV27SS001 DUE 10/29/2026 at 02:00PM -05:00 POC Buyer</p>
<p>SOURCES SOUGHT</p><p>NAICS Code 541330. Small businesses, SDVOSB and WOSB encouraged. Shared contract capacity $499M.</p>
<p>Place of Performance: Tulsa OK URL: <a href="https://sam.gov/opp/8a9774336ebf42febd40a998cce28cfd/view?">SAM</a></p>
<i>OutreachSystems Article Number: 20260929/PROCURE/0020</i></div>'''

def candidate():
    return m._parse_page('<table>'+HEADER+row()+'</table>',m.PAGE_URL)[0][0]

def test_index_dates_are_navigation_not_opportunities():
    rows,d=m._parse_page(INDEX,m.PAGE_URL)
    assert rows == [] and d['strategy_used']=='bulletin_index'
    assert d['bulletins'][0]['bulletin_date']=='2026-09-29'

def test_raw_http_thead_without_tr_and_nested_layout_tables():
    # The browser repairs this invalid HTML. html.parser preserves nested tables.
    daily='<table><table><table><thead>'+HEADER.replace('<tr>','').replace('</tr>','')+'</thead>'+row()+'</table></table></table>'
    rows,d=m._parse_page(daily,m.PAGE_URL)
    assert len(rows)==1 and d['rows_fetched']==1
    index=INDEX.replace('<tr><td>Date</td><td>Articles</td><td>Read</td></tr>', '<thead><th>Date</th><th>Articles</th><th>Read</th></thead>')
    assert len(m._parse_page(index,m.PAGE_URL)[1]['bulletins'])==1

def test_exact_fsg_gate_counts_and_retains_only_c():
    rows,d=m._parse_page(DAILY,m.PAGE_URL)
    assert len(rows)==2 and all(r['fsg']=='C' for r in rows)
    assert (d['rows_fetched'],d['matched_fsg_c'],d['skipped_non_c'],d['skipped_missing_fsg'])==(6,2,3,1)

@pytest.mark.parametrize('fsg',['Y','C219','c','',None])
def test_mapper_cannot_bypass_fsg_gate(fsg):
    c=m._parse_article(ARTICLE,candidate()); c['fsg']=fsg
    assert m._to_raw_intelligence_item(c,NOW) is None

def test_federal_fields_and_sam_identity_preserve_provenance():
    raw=m._to_raw_intelligence_item(m._parse_article(ARTICLE,candidate()),NOW)
    assert raw.external_id=='8a9774336ebf42febd40a998cce28cfd'
    assert raw.fields['solicitation_number']=='W912BV27SS001'
    assert raw.fields['proposal_due_at'].isoformat()=='2026-10-29T14:00:00-05:00'
    assert raw.fields['naics_code']=='541330'
    assert raw.fields['location_state']=='OK'
    assert raw.intelligence_category==IntelligenceCategory.PRE_SOLICITATION
    assert 'set_aside' not in raw.fields and 'estimated_value_high' not in raw.fields
    assert 'posted_at' not in raw.fields  # bulletin date is not original publication
    assert raw.raw['fsg']=='C' and '/article?' in raw.raw['detail_url']

def test_local_article_missing_fields_are_not_invented():
    article='''<div class="art-box"><h4>Texas - City of Port Arthur</h4>
    <p>C - ENGINEERING SERVICE FOR STREET &amp; DRAINAGE PROJECTS Due Date: 10/7/2026 3:00 PM URL <a href="https://www.portarthurtx.gov/bids.aspx?bidID=685">details</a></p>
    <i>OutreachSystems Article Number: 20260929/BID/1547</i></div>'''
    raw=m._to_raw_intelligence_item(m._parse_article(article,{**candidate(),'source_type':'bid'}),NOW)
    assert raw.fields['title']=='ENGINEERING SERVICE FOR STREET & DRAINAGE PROJECTS'
    assert raw.fields['proposal_due_at'].date()==date(2026,10,7)
    assert raw.fields['solicitation_number'] is None
    assert raw.fields['naics_code'] is None
    assert 'location_state' not in raw.fields and 'set_aside' not in raw.fields

def test_awards_never_become_live_opportunities():
    c=m._parse_article(ARTICLE,{**candidate(),'source_type':'awards'})
    assert c['category']==IntelligenceCategory.AWARD_INTELLIGENCE

@pytest.mark.parametrize('due',['Oct 29, 2026 @ 02:00 PM','2026-10-29 18:00:00','Closing On: 10/29/26 2:00 PM'])
def test_observed_local_deadline_formats(due):
    article=ARTICLE.replace('DUE 10/29/2026 at 02:00PM -05:00', 'Due Date: '+due)
    assert m._parse_article(article,candidate())['fields']['proposal_due_at'].date()==date(2026,10,29)

@pytest.mark.parametrize('html',['<div>Due 10/1/2026 <a href="/foo">Engineering services</a></div>','<table><tr><td>Date</td><td>Title</td><td>Read</td></tr></table>'])
def test_unknown_or_generic_shapes_fail_closed(html):
    rows,d=m._parse_page(html,m.PAGE_URL)
    assert not rows and d['strategy_used'] is None

def test_js_diagnostic_and_feed_detection():
    rows,d=m._parse_page('<body><div id="root"></div></body>',m.PAGE_URL)
    assert not rows and d['likely_javascript_rendered']
    _,d=m._parse_page('<link rel="alternate" type="application/rss+xml" href="/rss">'+INDEX,m.PAGE_URL)
    assert d['feed_link_found']=='/rss'

@pytest.mark.parametrize('url',['https://sam.gov/opp/8a9774336ebf42febd40a998cce28cfd/view','https://sam.gov/workspace/contract/opp/8a9774336ebf42febd40a998cce28cfd/view'])
def test_both_real_sam_url_forms_extract_the_same_notice(url):
    assert m._extract_sam_notice_id(url)=='8a9774336ebf42febd40a998cce28cfd'

def setup_fetch(monkeypatch, article=ARTICLE):
    calls=[]
    def get(client,method,url):
        calls.append(url)
        text=INDEX if url==m.PAGE_URL else DAILY if '/go?' in url else article
        return httpx.Response(200,text=text,request=httpx.Request(method,url))
    monkeypatch.setattr(m,'request_with_retry',get)
    return calls

def test_fetch_follows_bulletins_and_only_c_details(monkeypatch):
    calls=setup_fetch(monkeypatch)
    c=m.ApexMyBidMatchConnector(); rows=c.fetch(date(2026,9,1))
    assert len(rows)==1  # same SAM notice in two C rows is coalesced newest-first
    assert len(calls)==4
    assert 'seq=1' in calls[2] and 'seq=6' in calls[3]
    assert c.last_run_diagnostics['skipped_non_c']==3
    assert c.last_run_diagnostics['duplicate_notices_in_run']==1

def test_since_and_limit_are_explicit(monkeypatch):
    calls=setup_fetch(monkeypatch)
    c=m.ApexMyBidMatchConnector(); assert c.fetch(date(2026,9,30))==[]
    assert calls==[m.PAGE_URL]
    assert len(c.fetch(date(2026,9,1),limit=1))==1
    assert c.last_run_diagnostics['deferred_fsg_c_limit']==1

def test_detail_errors_identify_the_failed_rows(monkeypatch):
    setup_fetch(monkeypatch,article='<body>Access denied</body>')
    c=m.ApexMyBidMatchConnector(); assert c.fetch(date(2026,9,1))==[]
    assert c.last_run_diagnostics['mapping_errors']==2
    assert all(e['title'] and e['external_id'] and e['error'] for e in c.last_run_diagnostics['detail_errors'])

def test_fsg_mismatch_in_article_is_rejected():
    with pytest.raises(ValueError,match='FSG'):
        m._parse_article(ARTICLE.replace('C --','Y --'),candidate())
