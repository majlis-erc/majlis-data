<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:fn="http://www.w3.org/2005/xpath-functions" xmlns:tei="http://www.tei-c.org/ns/1.0"
    exclude-result-prefixes="fn tei xs"
    version="2.0">
    
    
  <!-- IdentityTransform -->
  <xsl:template match="/ | @* | node()">
        <xsl:copy>
            <xsl:apply-templates select="@* | node()" />
        </xsl:copy>
</xsl:template>
    
    <xsl:template match="tei:surrogates//tei:ptr/@target[contains(.,'nli.org.il')]">
            <xsl:attribute name="target">
                <xsl:value-of select="concat('https://www.nli.org.il/en/discover/manuscripts/hebrew-manuscripts/viewerpage?vid=MANUSCRIPTS#d=[[',
                    substring-after(., 'docid='), '-1]]')"/>
            </xsl:attribute>
    </xsl:template>
    
    <xsl:template match="tei:revisionDesc">
        <xsl:copy>
            <xsl:apply-templates select="@* | node()" />
            <change when="{format-date(fn:current-date(),'[Y]-[M,2]-[D,2]')}" who="#mmoliere" xmlns="http://www.tei-c.org/ns/1.0">Updated scan link.</change>
        </xsl:copy>
    </xsl:template>
</xsl:stylesheet>