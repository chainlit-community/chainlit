import { submitMessage } from '../../support/testUtils';

describe('Debug button', () => {
  it('renders a provider-neutral debug link with placeholders substituted', () => {
    cy.visit('/');
    submitMessage('Hello');

    cy.get("[data-step-type='assistant_message']")
      .should('have.length', 1)
      .first()
      .as('aiMessage');
    cy.get('@aiMessage').should('contain', 'Hello from the debug button test');

    cy.get('@aiMessage')
      .find('a[href^="https://debug.example.com/threads/"]')
      .should('have.length', 1)
      .invoke('attr', 'href')
      .should(
        'match',
        /^https:\/\/debug\.example\.com\/threads\/[^/[\]]+\/steps\/[^/[\]]+$/
      )
      .and('not.contain', '[thread_id]')
      .and('not.contain', '[step_id]');

    cy.get('body').should('not.contain.text', 'Literal AI');
  });
});
