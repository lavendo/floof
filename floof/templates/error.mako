<%inherit file="/base.mako" />

<%def name="title()">${http_status}</%def>

<section>
    <h1>${http_status}</h1>

    <p>${message}</p>

    % if outstanding_principals:

        % if len(outstanding_principals) == 1:
            <p>You may gain authorization by following the steps below:</p>
        % else:
            <p>You may gain authorization by following any of the following
            groups of steps:</p>
        % endif

        % for i, principal_group in enumerate(outstanding_principals):
            % if len(outstanding_principals) > 1:
                <h2>Alternative ${i + 1}</h2>
            % endif

            <ol class="standard-list">
            % if 'trusted:cert' in principal_group:
                % if len(request.user.valid_certificates) < 1:
                    <li>Generate and configure a client certificate</li>
                % endif
                <li>Present your client certificate for authentication</li>
            % endif
            % if 'auth:secure' in principal_group:
                <li>Configure your certificate authentication option to either
                'Require for login' or 'Require for Sensitive Operations only'</li>
            % endif
            % if 'trusted:browserid_recent' in principal_group:
                <li>Re-authenticate with your BrowserID</li>
            % elif 'trusted:browserid' in principal_group:
                <li>Authenticate with your BrowserID</li>
            % endif
            % if 'trusted:openid_recent' in principal_group:
                <li>Re-authenticate with your OpenID</li>
            % elif 'trusted:openid' in principal_group:
                <li>Authenticate with your OpenID</li>
            % endif
            </ol>
        % endfor

    % endif

</section>
