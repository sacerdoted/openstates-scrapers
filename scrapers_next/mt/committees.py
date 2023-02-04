from spatula import (
    HtmlPage,
    HtmlListPage,
    XPath,
    SelectorError,
    URL,
    SkipItem,
)
from openstates.models import ScrapeCommittee

import urllib.parse  # Need to urlencode a string


# This page contains information on every committee, except for administrative
# committees, which are handled by AdministrativeCommitteeList
class HouseSenateJointCommList(HtmlListPage):
    source = "http://laws.leg.mt.gov/legprd/law0240w$cmte.startup"

    # not(text()=" ") skips the blank option
    selector = XPath("//select[@name='P_COM_NM']/option[not(text()=' ')]/text()")

    def process_item(self, committee_title):

        # Need to get the latest session, it's the one that's pre-selected
        session = (
            XPath("//select[@name='P_SESS']/option[@selected='selected']")
            .match_one(self.root)
            .get("value")
        )

        # To build the member info url, special characters must be escaped
        committee_url_name = urllib.parse.quote_plus(committee_title)
        member_info_href = f"http://laws.leg.mt.gov/legprd/LAW0240W$CMTE.ActionQuery?P_SESS={session}&P_COM_NM={committee_url_name}&P_ACTN_DTM=&U_ACTN_DTM=&Z_ACTION2=Find"

        # Committee names may have abbreviations, replace them with the full word
        committee_title = committee_title.replace(
            "Approps ", "Appropriations "
        ).replace("Subcom ", "Subcommittee ")

        chamber = None
        parent = None
        classification = "committee"

        # These next steps will remove parts of the title
        # Each step builds on the last, so their order is important

        # 1) Determine the chamber from the title prefix
        house_prefix = "(H) "
        senate_prefix = "(S) "
        if committee_title.startswith(house_prefix):
            chamber = "lower"
            committee_title = committee_title[len(house_prefix) :]
        if committee_title.startswith(senate_prefix):
            chamber = "upper"
            committee_title = committee_title[len(senate_prefix) :]

        # 2) A joint prefix may exist
        joint_prefix = "Joint "
        if committee_title.startswith(joint_prefix):
            chamber = "legislature"
            committee_title = committee_title[len(joint_prefix) :]

        # 3) Select committee text isn't part of the name
        committee_title = committee_title.replace("Select Committee on ", "")

        committee_suffix = " Committee"
        if committee_title.endswith(committee_suffix):
            committee_title = committee_title[: -len(committee_suffix)]

        # 4) Check if a subcommittee
        subcommittee_info = committee_title.split(" Subcommittee on ")
        if len(subcommittee_info) == 2:
            committee_title = subcommittee_info[1]
            classification = "subcommittee"
            parent = subcommittee_info[0]

        # 5) The "Judicial Branch, Law Enforcement, and Justice" subcommittee
        #    is often called Public Safety, so append that to its name for
        #    added clarity
        if committee_title == "Judicial Branch, Law Enforcement, and Justice":
            committee_title += " (Public Safety)"

        # Build the committee object with calculated metadata
        com = ScrapeCommittee(
            name=committee_title,
            chamber=chamber,
            classification=classification,
            parent=parent,
        )
        com.add_source(member_info_href, note="Committee membership page")
        com.add_link(member_info_href, note="homepage")

        return HouseSenateJointCommDetail(
            {"com": com}, source=URL(member_info_href, timeout=30)
        )


class HouseSenateJointCommDetail(HtmlPage):
    def process_page(self):
        com = self.input.get("com")
        # The member table is the last table
        table = XPath("//table").match(self.root)[-1]
        rows = XPath("./tr[position()>1]").match(table)
        for row in rows:
            # Member name is inside of an <a> tag
            try:
                member = XPath("td[1]/a/text()").match_one(row)
            except SelectorError:
                # If member name isn't in an <a> tag, they are staff so skip
                continue

            # Member names may have double spaces, replace with single spaces
            member = member.replace("  ", " ")

            # Role is listed in the second column
            role = XPath("td[2]/text()").match_one(row)

            com.add_member(name=member, role=role)

        # Skip if no members found
        if len(com.members) == 0:
            raise SkipItem(f"No membership data found for: {com.name}")

        return com


# This page contains information on the Administrative committees only
# This site is a little buggy or perhaps there's a rate limiter involved
# Sometimes requests to this site do not return the expected html
class AdministrativeCommitteeList(HtmlListPage):
    source = "https://leg.mt.gov/committees/admincom/"
    selector = XPath("//*[@id='cont']/section/div/div[1]/div/div/div[1]/ul[1]/li/a[1]")

    def process_item(self, link):
        return CommitteeDetailsPage(
            self.source.url, source=URL(link.get("href"), timeout=30)
        )


class CommitteeDetailsPage(HtmlPage):
    # Committee pages on leg.mt.gov show member info
    def process_page(self):

        members = XPath("//p[@class='memberName']").match(self.root)

        # Grabbing the title from the breadcrumbs
        title = (
            XPath("//li[@class='breadcrumb-item active']")
            .match_one(self.root)
            .text_content()
        )

        # Some titles contain extra an extra word that isn't part of the title
        title = title.replace("Committee", "").strip()

        com = ScrapeCommittee(
            name=title,
            chamber="legislature",  # These are all joint committees
            classification="committee",  # No subcommittees here
        )
        com.add_source(self.source.url, note="Committee membership page")
        com.add_source(self.input, note="Committee list page")
        com.add_link(self.source.url, note="homepage")

        for member in members:
            title = member.text_content().strip().split("\n")
            title = [x.strip() for x in title if x.strip()]

            # First item in title is a member title like "SENATOR" or "REPRESENTATIVE"
            title = title[1:]

            role = "Member"
            # role info is sometime included and is formatted like "--Role"
            # It will always be the last value in the list.
            if title[-1].startswith("--"):
                role = title[-1][2:]  # 2 is len("--")
                title = title[:-1]  # Remove the role from the list

            # Remove party information from the list
            title = title[:-1]

            # The remaining elements in the list compose the name
            name = " ".join(title)

            # Name is in all caps, so make it title case
            name = name.title()

            com.add_member(name=name, role=role)

        # Skip if no members found
        if len(com.members) == 0:
            raise SkipItem(f"No membership data found for: {com.name}")

        return com
