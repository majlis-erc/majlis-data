<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:tei="http://www.tei-c.org/ns/1.0"
    xmlns:srophe="https://srophe.app" xmlns:saxon="http://saxon.sf.net/"
    xmlns:functx="http://www.functx.com" exclude-result-prefixes="xs" version="2.0">

    <!-- FILE OUTPUT PROCESSING -->
    <!-- specifies how the output file will look -->
    <xsl:output encoding="UTF-8" indent="yes" method="xml" name="xml"/>

    <!-- COLUMN NAME FORMATTING -->
    <!-- string appended to columns containing element names -->
    <xsl:variable name="element-suffix" select="'_element_'"/>
    <!-- string appended to columns containing attribute values, followed by attribute name. 
    Colons (for namespaces) should be indicated by a double hyphen -->
    <xsl:variable name="attribute-suffix" select="'_att_'"/>

    <!-- DIRECTORY -->
    <!-- specifies where the output TEI files should go -->
    <!-- !!! Change this to where you want the output files to be placed relative to the XML file being converted. 
        This should end with a trailing slash (/).-->
    <xsl:variable name="directory">../tei/</xsl:variable>

    <!-- !!! If true will put records lacking a URI into an "unresolved" folder and assign them a random ID. -->
    <xsl:variable name="process-unresolved" select="false()"/>

    <xsl:function name="srophe:create-element">
        <xsl:param name="content-column" as="node()*"/>
        <xsl:for-each select="$content-column[normalize-space(.) != '']">
            <xsl:variable name="column-name"
                select="replace(name(), concat($element-suffix, '.*$'), '')"/>
            <xsl:variable name="element"
                select="replace(name(), concat($column-name, $element-suffix), '')"/>
            <xsl:variable name="attributes"
                select="following-sibling::*[matches(name(), concat('^', $column-name, $attribute-suffix)) and normalize-space(.) != '']"/>
            <xsl:variable name="children"
                select="following-sibling::*[matches(name(), $element-suffix) and matches(name(), concat('^child_', $column-name))]"/>
            <xsl:element name="{$element}" namespace="http://www.tei-c.org/ns/1.0">
                <xsl:for-each select="$attributes">
                    <xsl:attribute
                        name="{replace(replace(name(),concat('.*',$attribute-suffix),''),'--',':')}"
                        select="."/>
                </xsl:for-each>
                <xsl:copy-of
                    select="
                        if ($children) then
                            srophe:create-element($children)
                        else
                            ()"/>
                <!-- Underscore (_) is used to trigger creating the element if it has no content.
                    Does this need to be a recursive function? -->
                <xsl:copy-of select="node()/normalize-space(replace(., '^_$', ''))"/>
            </xsl:element>
        </xsl:for-each>
    </xsl:function>

    <xsl:function name="functx:is-node-in-sequence-deep-equal" as="xs:boolean"
        xmlns:functx="http://www.functx.com">
        <xsl:param name="node" as="node()?"/>
        <xsl:param name="seq" as="node()*"/>

        <xsl:sequence
            select="
                some $nodeInSeq in $seq
                    satisfies deep-equal($nodeInSeq, $node)
                "/>

    </xsl:function>

    <xsl:function name="functx:distinct-deep" as="node()*" xmlns:functx="http://www.functx.com">
        <xsl:param name="nodes" as="node()*"/>

        <xsl:sequence
            select="
                for $seq in (1 to count($nodes))
                return
                    $nodes[$seq][not(functx:is-node-in-sequence-deep-equal(
                    ., $nodes[position() &lt; $seq]))]
                "/>

    </xsl:function>

    <xsl:function name="functx:substring-after-if-contains" as="xs:string?"
        xmlns:functx="http://www.functx.com">
        <xsl:param name="arg" as="xs:string?"/>
        <xsl:param name="delim" as="xs:string"/>

        <xsl:sequence
            select="
                if (contains($arg, $delim))
                then
                    substring-after($arg, $delim)
                else
                    $arg
                "/>

    </xsl:function>

    <xsl:function name="functx:name-test" as="xs:boolean" xmlns:functx="http://www.functx.com">
        <xsl:param name="testname" as="xs:string?"/>
        <xsl:param name="names" as="xs:string*"/>

        <xsl:sequence
            select="
                $testname = $names
                or
                $names = '*'
                or
                functx:substring-after-if-contains($testname, ':') =
                (for $name in $names
                return
                    substring-after($name, '*:'))
                or
                substring-before($testname, ':') =
                (for $name in $names[contains(., ':*')]
                return
                    substring-before($name, ':*'))
                "/>

    </xsl:function>

    <xsl:function name="functx:remove-attributes" as="element()"
        xmlns:functx="http://www.functx.com">
        <xsl:param name="elements" as="element()*"/>
        <xsl:param name="names" as="xs:string*"/>

        <xsl:for-each select="$elements">
            <xsl:element name="{node-name(.)}">
                <xsl:sequence
                    select="
                        (@*[not(functx:name-test(name(), $names))],
                        node())"
                />
            </xsl:element>
        </xsl:for-each>

    </xsl:function>

    <xsl:function name="srophe:remove-attributes" as="node()*">
        <xsl:param name="nodes" as="node()*"/>
        <xsl:param name="names" as="xs:string*"/>
        <xsl:for-each select="$nodes">
            <xsl:copy-of select="functx:remove-attributes(., $names)"/>
        </xsl:for-each>
    </xsl:function>

    <xsl:function name="srophe:attributes-from-matching-nodes-all-or-1st">
        <xsl:param name="matching-nodes" as="node()*"/>
        <xsl:param name="attribute-names" as="xs:string+"/>
        <xsl:param name="use-1st-value-only-mode" as="xs:boolean"/>
        <xsl:for-each select="$attribute-names">
            <xsl:variable name="attribute-name" select="."/>
            <xsl:variable name="matching-node-attributes"
                select="$matching-nodes/attribute::*[name() = $attribute-name]"/>
            <xsl:if test="$matching-node-attributes != ''">
                <xsl:choose>
                    <xsl:when test="$use-1st-value-only-mode">
                        <xsl:attribute name="{$attribute-name}"
                            select="$matching-nodes[1]/attribute::*[name() = $attribute-name]"/>
                    </xsl:when>
                    <xsl:otherwise>
                        <xsl:attribute name="{$attribute-name}"
                            select="distinct-values($matching-node-attributes)"/>
                    </xsl:otherwise>
                </xsl:choose>
            </xsl:if>
        </xsl:for-each>


    </xsl:function>

    <!-- Consolidates matching elements from different sources -->
    <xsl:function name="srophe:consolidate-matching-nodes" as="node()*">
        <xsl:param name="input-nodes" as="node()*"/>
        <xsl:param name="attributes-to-combine" as="xs:string*"/>
        <xsl:param name="attributes-to-ignore" as="xs:string*"/>
        <xsl:for-each
            select="functx:distinct-deep(srophe:remove-attributes($input-nodes, ($attributes-to-combine, $attributes-to-ignore)))">
            <xsl:variable name="this-node" select="."/>
            <xsl:variable name="matching-nodes"
                select="$input-nodes[deep-equal($this-node, functx:remove-attributes(., ($attributes-to-combine, $attributes-to-ignore)))]"/>
            <xsl:element name="{$this-node/name()}" namespace="http://www.tei-c.org/ns/1.0">
                <xsl:copy-of
                    select="srophe:attributes-from-matching-nodes-all-or-1st($matching-nodes, $attributes-to-ignore, true())"/>
                <xsl:for-each select="$this-node/@*">
                    <xsl:attribute name="{name()}" select="."/>
                </xsl:for-each>
                <xsl:copy-of
                    select="srophe:attributes-from-matching-nodes-all-or-1st($matching-nodes, $attributes-to-combine, false())"/>
                <xsl:copy-of select="$this-node/node()"/>
            </xsl:element>
        </xsl:for-each>
    </xsl:function>

    <!-- MAIN TEMPLATE -->
    <!-- processes each row of the spreadsheet -->
    <xsl:template match="/root">
        <!-- creates ids for new persons. -->
        <!-- ??? How should we deal with matched persons, where the existing TEI records need to be supplemented? -->
        <xsl:for-each select="row[not(contains(., '***'))]">
            <xsl:variable name="record-id">
                <!-- gets a record ID from the New_URI column, or generates one if that column is blank -->
                <xsl:choose>
                    <xsl:when test="New_URI != ''">
                        <xsl:value-of select="New_URI"/>
                    </xsl:when>
                    <xsl:otherwise>
                        <xsl:value-of select="concat('unresolved-', generate-id())"/>
                    </xsl:otherwise>
                </xsl:choose>
            </xsl:variable>

            <!-- creates the URI from the record ID -->
            <xsl:variable name="record-uri" select="concat('https://majlis.net/person/', New_URI)"/>

            <xsl:variable name="headword-column-names"
                select="
                    for $name in ./*[matches(., '#majlis-headword')]/name()
                    return
                        replace($name, '_Attribute', '')"/>

            <!-- creates a variable containing the path of the file to be created for this record, in the location defined by $directory -->
            <xsl:variable name="filename">
                <xsl:choose>
                    <!-- tests whether there is sufficient data to create a complete record. If not, puts it in an 'incomplete' folder inside the $directory -->
                    <xsl:when test="empty(./*[name() = $headword-column-names]) and New_URI != ''">
                        <xsl:value-of
                            select="concat($directory, '/incomplete/', $record-id, '.xml')"/>
                    </xsl:when>
                    <!-- if record is complete and has a URI, puts it in the $directory folder -->
                    <xsl:when test="New_URI != ''">
                        <xsl:value-of select="concat($directory, $record-id, '.xml')"/>
                    </xsl:when>
                    <!-- if record doesn't have a URI, puts it in 'unresolved' folder inside the $directory  -->
                    <xsl:otherwise>
                        <xsl:if test="$process-unresolved">
                            <xsl:value-of
                                select="concat($directory, 'unresolved/', $record-id, '.xml')"/>
                        </xsl:if>
                    </xsl:otherwise>
                </xsl:choose>
            </xsl:variable>

            <!-- creates the XML file, if the filename has been sucessfully created. -->
            <xsl:if test="$filename != ''">
                <xsl:result-document href="{$filename}" format="xml">
                    <!-- adds the xml-model instruction with the link to the Syriaca.org validator -->
                    <xsl:processing-instruction name="xml-model">
                    <xsl:text>href="http://syriaca.org/documentation/syriaca-tei-main.rnc" type="application/relax-ng-compact-syntax"</xsl:text>
                </xsl:processing-instruction>

                    <xsl:variable name="content-cells"
                        select="./*[matches(name(), $element-suffix) and not(matches(name(), '^child'))]"/>

                    <xsl:variable name="content-cells-converted"
                        select="srophe:create-element($content-cells)"/>

                    <xsl:variable name="content-cells-converted-consolidated"
                        select="srophe:consolidate-matching-nodes($content-cells-converted, ('srophe-tags', 'source', 'resp'), 'xml:id')"/>

                    <TEI xml:lang="en" xmlns="http://www.tei-c.org/ns/1.0">
                        <xsl:variable name="en-headword"
                            select="$content-cells-converted/self::*[@srophe-tags = '#majlis-headword' and starts-with(@xml:lang, 'en')]"/>
                        <!-- Adds header from the header template -->
                        <xsl:call-template name="header">
                            <xsl:with-param name="record-id" select="$record-id"/>
                            <xsl:with-param name="converted-columns"
                                select="$content-cells-converted/*"/>
                            <xsl:with-param name="en-headword" select="$en-headword"/>
                        </xsl:call-template>
                        <text>
                            <body>
                                <listPerson>
                                    <person>
                                        <!-- creates an @xml:id and adds it to the person element -->
                                        <xsl:attribute name="xml:id"
                                            select="concat('person-', $record-id)"/>
                                        <xsl:copy-of select="$content-cells-converted-consolidated"
                                            xpath-default-namespace="http://www.tei-c.org/ns/1.0"/>
                                    </person>
                                </listPerson>
                            </body>
                        </text>
                    </TEI>
                </xsl:result-document>
            </xsl:if>
        </xsl:for-each>
    </xsl:template>
    <!-- TEI HEADER TEMPLATE -->
    <!-- ??? Update the following! -->
    <!-- !!! This will need to be updated for each new spreadsheet that has different contributors -->
    <xsl:template name="header" xmlns="http://www.tei-c.org/ns/1.0">
        <xsl:param name="record-id"/>
        <xsl:param name="converted-columns"/>
        <xsl:param name="en-headword"/>
        <xsl:variable name="en-title">
            <!-- checks whether there is an English Syriaca headword. If not, just uses the record-id as the page title. -->
            <xsl:choose>
                <xsl:when test="$en-headword">
                    <xsl:value-of select="$en-headword"/>
                </xsl:when>
                <xsl:otherwise>Person <xsl:value-of select="$record-id"/></xsl:otherwise>
            </xsl:choose>
        </xsl:variable>
        <xsl:variable name="anonymous-description">
            <!-- grabs the anonymous description, if there is one. -->
            <xsl:choose>
                <xsl:when test="$converted-columns/*[@srophe-tags = '#anonymous-description']">
                    <xsl:value-of
                        select="$converted-columns/*[@srophe-tags = '#anonymous-description']"/>
                </xsl:when>
            </xsl:choose>
        </xsl:variable>
        <xsl:variable name="majlis-headword">
            <!-- grabs the Syriac headword, if there is one. -->
            <xsl:choose>
                <xsl:when
                    test="$converted-columns/*[@srophe-tags = '#majlis-headword' and starts-with(@xml:lang, 'syr')]">
                    <xsl:value-of
                        select="$converted-columns/*[@srophe-tags = '#majlis-headword' and starts-with(@xml:lang, 'syr')]"
                    />
                </xsl:when>
            </xsl:choose>
        </xsl:variable>
        <!-- combines the English and Syriac headwords to make the record title -->
        <xsl:variable name="record-title">
            <xsl:value-of select="$en-title"/>
            <xsl:choose>
                <xsl:when test="string-length($anonymous-description)"> — <xsl:value-of
                        select="$anonymous-description"/></xsl:when>
                <xsl:when test="string-length($majlis-headword)"> — <foreign xml:lang="syr"
                            ><xsl:value-of select="$majlis-headword"/></foreign></xsl:when>
            </xsl:choose>
        </xsl:variable>
        <teiHeader>
            <fileDesc>
                <titleStmt>
                    <title level="a" xml:lang="en">
                        <xsl:copy-of select="$record-title"/>
                    </title>
                    <title level="m" xml:lang="en">MAJLIS: The Transformation of Jewish Literature
                        in Arabic in the Islamicate World</title>
                    <sponsor ref="https://www.uni-muenchen.de">
                        <orgName>Ludwig Maximilian University of Munich</orgName> (<orgName
                            xml:lang="de">Ludwig-Maximilians-Universität München</orgName>) </sponsor>
                    <sponsor ref="http://www.naher-osten.uni-muenchen.de">
                        <orgName>Institute of Near and Middle Eastern Studies</orgName> (<orgName
                            xml:lang="de">Institut für den Nahen und Mittleren Osten</orgName>) </sponsor>
                    <funder ref="https://erc.europa.eu/">
                        <orgName>ERC: European Research Council</orgName> (<orgName xml:lang="de"
                            >Europäischer Forschungsrat</orgName>) </funder>
                    <principal ref="#rvollandt">Ronny Vollandt</principal>

                    <!-- EDITORS -->
                    <editor xml:id="rvollandt" role="general"
                        ref=" 
                        https://www.naher-osten.uni-muenchen.de/personen/professoren/ronny_vollandt/index.html
                        http://orcid.org/0000-0002-1702-2981
                        https://viaf.org/viaf/309581349"
                        >Ronny Vollandt</editor>
                    <editor xml:id="gschwarb" role="contributor"
                        ref="
                        https://www.naher-osten.uni-muenchen.de/personen/wiss_ma/gregor_schwarb/index.html
                        http://orcid.org/0000-0002-9090-1878
                        https://viaf.org/viaf/90488472"
                        >Gregor Schwarb</editor>
                    <editor xml:id="ngibson" role="contributor"
                        ref="
                        https://www.naher-osten.uni-muenchen.de/personen/wiss_ma/gibson/index.html
                        http://orcid.org/0000-0003-0786-8075
                        https://viaf.org/viaf/59147905242279092527"
                        >Nathan P. Gibson</editor>
                    <editor xml:id="mmoliere" role="contributor"
                        ref="
                        https://www.naher-osten.uni-muenchen.de/personen/wiss_ma/maximilian_de_moliere/index.html
                        https://orcid.org/0000-0002-2168-8655
                        http://viaf.org/viaf/65156495392717561393"
                        >Maximilian de Molière</editor>

                    <!-- CREATOR -->
                    <!-- designates the editor responsible for creating this person record (may be different from the file creator) -->
                    <editor role="creator" ref="#ngibson">Nathan P. Gibson</editor>
                    <editor role="creator" ref="#mmoliere">Maximilian de Molière</editor>

                    <!-- CONTRIBUTORS -->
                    <respStmt>
                        <resp>Original tabular architecture and XSLT script by</resp>
                        <name type="person" ref="#ngibson">Nathan P. Gibson</name>
                    </respStmt>
                    <respStmt>
                        <resp>Adaption of the tabular architecture and XSLT script for MAJLIS and
                            conversion into TEI-XML format by</resp>
                        <name type="person" ref="#mmoliere">Maximilian de Molière</name>
                    </respStmt>
                    <respStmt>
                        <resp>Data entry into Google Sheets by</resp>
                        <name type="person" ref="#nurbiczek">Nadine Urbiczek</name>
                    </respStmt>
                    <respStmt>
                        <resp>Data entry into Google Sheets by</resp>
                        <name type="person" ref="#lfroschmeier">Lukas Froschmeier</name>
                    </respStmt>
                    <!--<respStmt>
                        <resp>English and Arabic name entry, 
                            matching with external records<xsl:if test="matches(name_checking_credit,'#rschmahl')">, checking for typographical 
                            errors in headword name, abstract, and references</xsl:if> by</resp>
                        <name type="person" ref="#rschmahl">Robin Schmahl</name>
                    </respStmt>
                    <xsl:if test="matches(arabic_checking_credit,'#hfriedel')">
                    <respStmt>
                        <resp>Adding names in Arabic script by</resp>
                        <name type="person" ref="#hfriedel">Hanna Friedel</name>
                    </respStmt>
                    </xsl:if>-->
                    <respStmt>
                        <resp>Original data architecture of TEI person records for Srophé by</resp>
                        <name type="person"
                            ref="http://syriaca.org/documentation/editors.xml#dmichelson">David A.
                            Michelson</name>
                    </respStmt>
                    <respStmt>
                        <resp>Srophé app design and development by</resp>
                        <name type="person"
                            ref="http://syriaca.org/documentation/editors.xml#wsalesky">Winona
                            Salesky</name>
                    </respStmt>
                </titleStmt>
                <editionStmt>
                    <edition n="0.6.0-dev"/>
                </editionStmt>
                <publicationStmt>
                    <authority>
                        <ref target="https://majlis.net">Majlis.net</ref>
                    </authority>
                    <idno type="URI">https://majlis.net/person/<xsl:value-of select="$record-id"
                        />/tei</idno>
                    <availability>
                        <licence target="http://creativecommons.org/licenses/by/3.0/">
                            <p>Distributed under a Creative Commons Attribution 4.0 International
                                (CC BY 4.0) License.</p>
                            <!-- !!! If copyright material is included, the following should be adapted and used. -->
                            <!--<p>This entry incorporates copyrighted material from the following work(s):
                                    <listBibl>
                                            <bibl>
                                                <ptr>
                                                    <xsl:attribute name="target" select="'foo1'"/>
                                                </ptr>
                                            </bibl>
                                            <bibl>
                                                <ptr>
                                                    <xsl:attribute name="target" select="'foo2'"/>
                                                </ptr>
                                            </bibl>
                                    </listBibl>
                                    <note>used under a Creative Commons Attribution license <ref target="http://creativecommons.org/licenses/by/3.0/"/></note>
                                </p>-->
                        </licence>
                    </availability>
                    <date>2021-10-23+02:00</date>
                    <!--<date>
                        <xsl:value-of select="current-date()"/>
                    </date>-->
                </publicationStmt>

                <sourceDesc>
                    <p>Born digital.</p>
                </sourceDesc>
            </fileDesc>

            <!-- ADAPT TO MAJLIS TEI DOCUMENTATION -->
            <encodingDesc>
                <editorialDecl>
                    <p>This record created following the Syriaca.org guidelines. Documentation
                        available at: <ref target="http://syriaca.org/documentation"
                            >http://syriaca.org/documentation</ref>.</p>
                    <interpretation>
                        <p>Approximate dates described in terms of centuries or partial centuries
                            have been interpreted as documented in <ref
                                target="http://syriaca.org/documentation/dates.html">Syriaca.org
                                Dates</ref>.</p>
                    </interpretation>
                </editorialDecl>
                <classDecl>
                    <taxonomy>
                        <category xml:id="majlis-headword">
                            <catDesc>The name used by the project for document titles, citation, and
                                disambiguation. These names have been created according to the
                                majlis.net guidelines for headwords.</catDesc>
                        </category>
                        <category xml:id="canon">
                            <catDesc>This name presents the full canonical form used by the MAJLIS project.</catDesc>
                        </category>
                        <!--<category xml:id="syriaca-anglicized">
                            <catDesc>An anglicized version of a name, included to facilitate
                                searching.</catDesc>
                        </category>
                        <category xml:id="ektobe-headword">
                            <catDesc>The name used by e-Ktobe as a standardized name form.</catDesc>
                        </category>
                    </taxonomy>
                    <taxonomy>
                        <category xml:id="syriaca-author">
                            <catDesc>A person who is relevant to the Guide to Syriac
                                Authors</catDesc>
                        </category>-->
                    </taxonomy>
                </classDecl>
            </encodingDesc>
            <profileDesc>
                <langUsage>
                    <!-- !!! Additional languages, if used, should be added here. -->
                    <language ident="en">English</language>
                    <language ident="ar">Arabic</language>
                    <language ident="he">Hebrew</language>
                    <language ident="fr">French</language>
                    <language ident="de">German</language>
                    <language ident="la">Latin</language>
                    <language ident="ar-Hebr">Arabic text in Hebrew characters</language>
                    <language ident="ar-Latn">Arabic text in Latin characters</language>
                    <language ident="he-Latn">Hebrew text in Latin characters</language>
                </langUsage>
            </profileDesc>
            <revisionDesc status="draft">

                <!-- FILE CREATOR -->
                <xsl:if test="index-of(tokenize(changelog, ','), '1')">
                    <change who="http://majlis.net/documentation/editors.xml#ngibson" n="0.2"
                        when="2020-06-08+02:00" xml:id="change-1">CREATED: person from spreadsheet
                        https://docs.google.com/spreadsheets/d/1ujiT91ua3sA-WX86OWpuE-gDD_E-zONpI1dP70pXdWw/edit#gid=0.
                        The canonical record is currently in the spreadsheet. Changes should be made
                        there. THIS FILE SHOULD NOT BE MANUALLY EDITED!</change>
                </xsl:if>

                <!-- PLANNED CHANGES -->
                <!-- ??? Are there any change @type='planned' ? -->
            </revisionDesc>
        </teiHeader>
    </xsl:template>
</xsl:stylesheet>
